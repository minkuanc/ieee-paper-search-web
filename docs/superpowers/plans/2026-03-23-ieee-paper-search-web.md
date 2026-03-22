# IEEE Paper Search Web App — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the IEEE Paper Search desktop app as a local web app — FastAPI backend + React/Vite frontend — with identical search/download/Excel functionality and real-time SSE progress.

**Architecture:** FastAPI backend on port 8000 handles search (via IEEE Xplore internal API), PDF download (via undetected-chromedriver + Selenium), and Excel generation. React/Vite frontend on port 5173 proxies `/api/*` to the backend. SSE streams per-paper download progress with replay support via `Last-Event-ID`.

**Tech Stack:** Python 3.9+, FastAPI, uvicorn, undetected-chromedriver, openpyxl, requests, React 18, Vite, plain CSS.

**Desktop app source to copy from:** `/Users/minkuanc/Claude/ieee_search_app/`

---

## File Map

### Backend (`ieee-paper-search-web/backend/`)

| File | Responsibility |
|---|---|
| `scraper.py` | Copied from desktop app — IEEE search + PDF download (no changes) |
| `excel_writer.py` | Copied from desktop app — Excel write + dedup (no changes) |
| `main.py` | FastAPI app: CORS, routes, job store, SSE generator, cleanup task |
| `requirements.txt` | Backend Python dependencies |
| `tests/test_api.py` | Unit tests for API routes using FastAPI `TestClient` |

### Frontend (`ieee-paper-search-web/frontend/`)

| File | Responsibility |
|---|---|
| `package.json` | React 18 + Vite dependencies |
| `vite.config.js` | Proxy `/api` → `http://localhost:8000` |
| `index.html` | HTML shell |
| `src/main.jsx` | React entry point |
| `src/App.jsx` | Root component — owns all shared state |
| `src/App.css` | Global styles |
| `src/components/KeywordInput.jsx` | Keyword inputs + Search button |
| `src/components/ResultsTable.jsx` | Paper table, checkboxes, truncation banner |
| `src/components/DownloadPanel.jsx` | Folder input, Download button, SSE progress, Excel link |

---

## Task 1: Project Scaffold

**Files:**
- Create: `ieee-paper-search-web/backend/scraper.py`
- Create: `ieee-paper-search-web/backend/excel_writer.py`
- Create: `ieee-paper-search-web/backend/requirements.txt`
- Create: `ieee-paper-search-web/backend/tests/__init__.py`

- [ ] **Step 1: Copy scraper and excel_writer from the desktop app**

```bash
cd /Users/minkuanc/Claude/ieee-paper-search-web
mkdir -p backend/tests frontend/src/components
cp ../ieee_search_app/scraper.py backend/scraper.py
cp ../ieee_search_app/excel_writer.py backend/excel_writer.py
touch backend/tests/__init__.py
```

- [ ] **Step 2: Create `backend/requirements.txt`**

```
fastapi>=0.111
uvicorn[standard]>=0.29
requests>=2.31
undetected-chromedriver>=3.5
openpyxl>=3.1
pytest>=8.0
httpx>=0.27
```

- [ ] **Step 3: Install backend dependencies**

```bash
cd backend && pip install -r requirements.txt
```

Expected: all packages install without errors.

- [ ] **Step 4: Commit scaffold**

```bash
cd /Users/minkuanc/Claude/ieee-paper-search-web
git init
git add backend/
git commit -m "feat: scaffold backend with copied scraper and excel_writer"
```

---

## Task 2: FastAPI App Skeleton + CORS

**Files:**
- Create: `backend/main.py`
- Create: `backend/tests/test_api.py`

- [ ] **Step 1: Write a failing smoke test**

Create `backend/tests/test_api.py`:

```python
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}

def test_cors_header():
    r = client.options(
        "/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert r.headers.get("access-control-allow-origin") == "*"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_api.py::test_health -v
```

Expected: `ImportError` or `ModuleNotFoundError` — `main` does not exist yet.

- [ ] **Step 3: Create `backend/main.py` with health route and CORS**

```python
import asyncio
import json
import os
import re
import threading
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from scraper import PDFDownloader, search_papers
from excel_writer import ExcelWriter

# ── job store ─────────────────────────────────────────────────────────────────
jobs: dict[str, dict] = {}
JOB_TTL = 3600  # seconds


async def _cleanup_jobs():
    """Remove jobs older than JOB_TTL every 5 minutes."""
    while True:
        await asyncio.sleep(300)
        now = time.time()
        stale = [jid for jid, j in list(jobs.items()) if now - j["created_at"] > JOB_TTL]
        for jid in stale:
            jobs.pop(jid, None)


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(_cleanup_jobs())
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # localhost-only deployment
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_api.py -v
```

Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/tests/test_api.py
git commit -m "feat: FastAPI skeleton with CORS and health endpoint"
```

---

## Task 3: `POST /api/search` Endpoint

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/tests/test_api.py`

- [ ] **Step 1: Write failing test for search endpoint**

Add to `backend/tests/test_api.py`:

```python
from unittest.mock import patch

def test_search_returns_papers():
    fake_papers = [
        {"title": "Paper A", "year": 2024, "authors": "Smith", "venue": "IEEE", "doi": "10.1/a", "url": "http://x", "pdf_link": "/a"}
    ]
    with patch("main.search_papers", return_value=(fake_papers, False, 1)):
        r = client.post("/api/search", json={"keywords": ["deep learning"], "years_back": 3})
    assert r.status_code == 200
    data = r.json()
    assert len(data["papers"]) == 1
    assert data["truncated"] is False
    assert data["total"] == 1

def test_search_empty_keywords_returns_400():
    r = client.post("/api/search", json={"keywords": [], "years_back": 3})
    assert r.status_code == 400
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && python -m pytest tests/test_api.py::test_search_returns_papers -v
```

Expected: FAIL — route does not exist yet.

- [ ] **Step 3: Add `/api/search` to `main.py`**

Add after the health route:

```python
class SearchRequest(BaseModel):
    keywords: list[str]
    years_back: int = 3


@app.post("/api/search")
def api_search(req: SearchRequest):
    kws = [k.strip() for k in req.keywords if k.strip()]
    if not kws:
        raise HTTPException(status_code=400, detail="At least one keyword is required")
    papers, truncated, total = search_papers(kws, req.years_back)
    return {"papers": papers, "truncated": truncated, "total": total}
```

- [ ] **Step 4: Run tests**

```bash
cd backend && python -m pytest tests/test_api.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/tests/test_api.py
git commit -m "feat: POST /api/search endpoint"
```

---

## Task 4: `POST /api/download` — Validation + Job Creation

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/tests/test_api.py`

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/test_api.py`:

```python
import tempfile

def test_download_nonexistent_folder_returns_400():
    r = client.post("/api/download", json={
        "papers": [{"title": "P", "year": 2024, "authors": "", "venue": "", "doi": "x", "url": "http://x", "pdf_link": ""}],
        "dest_folder": "/nonexistent/path/xyz",
        "keywords": ["deep learning"]
    })
    assert r.status_code == 400
    assert "does not exist" in r.json()["detail"]

def test_download_valid_folder_returns_job_id():
    with tempfile.TemporaryDirectory() as tmp:
        with patch("main.threading.Thread"):  # don't actually start download
            r = client.post("/api/download", json={
                "papers": [{"title": "P", "year": 2024, "authors": "", "venue": "", "doi": "x", "url": "http://x", "pdf_link": ""}],
                "dest_folder": tmp,
                "keywords": ["deep learning"]
            })
    assert r.status_code == 200
    assert "job_id" in r.json()
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && python -m pytest tests/test_api.py::test_download_nonexistent_folder_returns_400 -v
```

Expected: FAIL — route does not exist.

- [ ] **Step 3: Add `/api/download` to `main.py`**

Add after the search route:

```python
class PaperItem(BaseModel):
    title: str
    year: int
    authors: str
    venue: str
    doi: str
    url: str
    pdf_link: str = ""


class DownloadRequest(BaseModel):
    papers: list[PaperItem]
    dest_folder: str
    keywords: list[str]


def _sanitize_folder_name(kw: str) -> str:
    return re.sub(r'[\\/:*?"<>| ]', "_", kw)


def _run_download(job_id: str, loop: asyncio.AbstractEventLoop):
    """Background thread: download each paper and push SSE events."""
    job = jobs[job_id]
    downloader = PDFDownloader()
    total = len(job["papers"])
    try:
        for idx, paper in enumerate(job["papers"]):
            local_path, status = downloader.download(paper, job["root"])
            event = {
                "index": idx + 1,
                "total": total,
                "title": paper["title"],
                "status": status,
                "local_path": local_path,
                "done": idx == total - 1,
            }
            job["results"].append(event)
            loop.call_soon_threadsafe(job["queue"].put_nowait, event)
        # Write Excel
        excel_path = os.path.join(job["root"], "papers.xlsx")
        writer = ExcelWriter(excel_path)
        writer.append_papers([
            {**jobs[job_id]["papers"][i], "local_path": e["local_path"], "status": e["status"]}
            for i, e in enumerate(job["results"])
        ])
        writer.save()
        job["excel_path"] = excel_path
    finally:
        job["done"] = True
        downloader.close()


@app.post("/api/download")
async def api_download(req: DownloadRequest):
    if not os.path.exists(req.dest_folder):
        raise HTTPException(status_code=400, detail="Destination folder does not exist")
    if not os.access(req.dest_folder, os.W_OK):
        raise HTTPException(status_code=400, detail="Destination folder is not writable")

    root_name = "_".join(_sanitize_folder_name(k) for k in req.keywords if k.strip())
    root = os.path.join(req.dest_folder, root_name)
    os.makedirs(root, exist_ok=True)

    job_id = str(uuid.uuid4())
    loop = asyncio.get_event_loop()
    jobs[job_id] = {
        "papers": [p.model_dump() for p in req.papers],
        "root": root,
        "results": [],
        "queue": asyncio.Queue(),
        "done": False,
        "excel_path": None,
        "created_at": time.time(),
    }

    t = threading.Thread(target=_run_download, args=(job_id, loop), daemon=True)
    t.start()
    return {"job_id": job_id}
```

- [ ] **Step 4: Run tests**

```bash
cd backend && python -m pytest tests/test_api.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/tests/test_api.py
git commit -m "feat: POST /api/download with validation and background job"
```

---

## Task 5: SSE Progress, Status, and Excel Endpoints

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/tests/test_api.py`

- [ ] **Step 1: Write failing test for status endpoint**

Add to `backend/tests/test_api.py`:

```python
def test_status_unknown_job_returns_404():
    r = client.get("/api/download/nonexistent-id/status")
    assert r.status_code == 404

def test_status_done_job():
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "results": [
            {"status": "Downloaded", "local_path": "/f/p.pdf", "done": True, "index": 1, "total": 1, "title": "T"},
        ],
        "root": "/tmp/root",
        "done": True,
        "excel_path": "/tmp/root/papers.xlsx",
        "created_at": time.time(),
        "papers": [],
        "queue": asyncio.Queue(),
    }
    r = client.get(f"/api/download/{job_id}/status")
    assert r.status_code == 200
    data = r.json()
    assert data["downloaded"] == 1
    assert data["failed"] == 0
    assert data["done"] is True
```

Add the import at the top of `test_api.py`: `import uuid`, `from main import jobs`.

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && python -m pytest tests/test_api.py::test_status_unknown_job_returns_404 -v
```

Expected: FAIL — route does not exist.

- [ ] **Step 3: Add SSE, status, and excel routes to `main.py`**

```python
@app.get("/api/download/{job_id}/progress")
async def api_progress(job_id: str, request: Request):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]
    last_event_id = request.headers.get("last-event-id")
    replay_from = int(last_event_id) + 1 if last_event_id and last_event_id.isdigit() else 0

    async def event_stream():
        # Replay buffered events on reconnect
        for i, event in enumerate(job["results"][replay_from:], start=replay_from):
            yield f"id: {i}\ndata: {json.dumps(event)}\n\n"
            if event.get("done"):
                return

        # Stream live events
        live_idx = len(job["results"])
        while True:
            event = await job["queue"].get()
            yield f"id: {live_idx}\ndata: {json.dumps(event)}\n\n"
            live_idx += 1
            if event.get("done"):
                return

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/download/{job_id}/status")
def api_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    downloaded = sum(1 for r in job["results"] if r["status"] == "Downloaded")
    failed = sum(1 for r in job["results"] if r["status"] != "Downloaded")
    return {
        "downloaded": downloaded,
        "failed": failed,
        "root_folder": job["root"],
        "done": job["done"],
    }


@app.get("/api/download/{job_id}/excel")
def api_excel(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    if not job["done"]:
        raise HTTPException(status_code=425, detail="Download not yet complete")
    excel_path = job.get("excel_path")
    if not excel_path or not os.path.exists(excel_path):
        raise HTTPException(status_code=404, detail="Excel file not found")
    return FileResponse(
        excel_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="papers.xlsx",
    )
```

- [ ] **Step 4: Run all tests**

```bash
cd backend && python -m pytest tests/test_api.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Manual smoke test — start the backend**

```bash
cd backend && uvicorn main:app --reload --port 8000
```

Expected: server starts, visit `http://localhost:8000/health` → `{"status":"ok"}`

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/tests/test_api.py
git commit -m "feat: SSE progress, status, and Excel download endpoints"
```

---

## Task 6: Frontend Scaffold (Vite + React)

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.js`
- Create: `frontend/index.html`
- Create: `frontend/src/main.jsx`

- [ ] **Step 1: Verify Node.js is available**

```bash
node --version && npm --version
```

If Node.js is not installed: download from `https://nodejs.org` (LTS version) and install before continuing.

- [ ] **Step 2: Scaffold the Vite + React project**

```bash
cd /Users/minkuanc/Claude/ieee-paper-search-web
npm create vite@latest frontend -- --template react
cd frontend && npm install
```

Expected: `frontend/` created with `src/App.jsx`, `src/main.jsx`, `index.html`, `package.json`, `vite.config.js`.

- [ ] **Step 3: Configure the Vite proxy**

Edit `frontend/vite.config.js` to proxy API calls to the FastAPI backend:

```js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
```

- [ ] **Step 4: Verify dev server starts**

```bash
cd frontend && npm run dev
```

Expected: Vite dev server starts on `http://localhost:5173`, browser shows the default Vite+React page.

- [ ] **Step 5: Commit**

```bash
cd /Users/minkuanc/Claude/ieee-paper-search-web
git add frontend/
git commit -m "feat: scaffold React/Vite frontend with API proxy"
```

---

## Task 7: `KeywordInput` Component

**Files:**
- Create: `frontend/src/components/KeywordInput.jsx`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/App.css`

- [ ] **Step 1: Create `KeywordInput.jsx`**

```jsx
import { useState } from 'react'

export default function KeywordInput({ onSearch, loading }) {
  const [keywords, setKeywords] = useState(['', '', ''])

  function updateKeyword(i, val) {
    setKeywords(prev => prev.map((k, idx) => idx === i ? val : k))
  }

  function addKeyword() {
    setKeywords(prev => [...prev, ''])
  }

  function handleSearch() {
    const active = keywords.map(k => k.trim()).filter(Boolean)
    if (active.length === 0) return
    onSearch(active)
  }

  return (
    <div className="keyword-section">
      <div className="keyword-inputs">
        {keywords.map((kw, i) => (
          <input
            key={i}
            type="text"
            value={kw}
            placeholder={`Keyword ${i + 1}`}
            onChange={e => updateKeyword(i, e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSearch()}
            className="keyword-input"
          />
        ))}
      </div>
      <div className="keyword-actions">
        <button onClick={addKeyword} className="btn-secondary">+ Add Keyword</button>
        <button onClick={handleSearch} disabled={loading} className="btn-primary">
          {loading ? 'Searching…' : 'Search'}
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Wire into `App.jsx` temporarily to verify it renders**

Replace `frontend/src/App.jsx` contents with:

```jsx
import { useState } from 'react'
import KeywordInput from './components/KeywordInput'
import './App.css'

export default function App() {
  const [loading, setLoading] = useState(false)
  const [papers, setPapers] = useState([])
  const [truncated, setTruncated] = useState(false)
  const [total, setTotal] = useState(0)
  const [selectedIndices, setSelectedIndices] = useState(new Set())
  const [keywords, setKeywords] = useState([])

  async function handleSearch(kws) {
    setLoading(true)
    setKeywords(kws)
    try {
      const res = await fetch('/api/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ keywords: kws, years_back: 3 }),
      })
      const data = await res.json()
      setPapers(data.papers)
      setTruncated(data.truncated)
      setTotal(data.total)
      setSelectedIndices(new Set())
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app">
      <h1>IEEE Paper Search</h1>
      <KeywordInput onSearch={handleSearch} loading={loading} />
      <p>{papers.length} papers loaded</p>
    </div>
  )
}
```

- [ ] **Step 3: Add base styles to `App.css`**

Replace `frontend/src/App.css`:

```css
*, *::before, *::after { box-sizing: border-box; }

body { font-family: system-ui, sans-serif; margin: 0; background: #f5f7fa; color: #1a1a2e; }

.app { max-width: 1100px; margin: 0 auto; padding: 24px; }

h1 { color: #00539b; margin-bottom: 20px; }

.keyword-section { background: white; border-radius: 8px; padding: 16px; margin-bottom: 16px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }

.keyword-inputs { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }

.keyword-input { border: 1px solid #ccc; border-radius: 4px; padding: 6px 10px; font-size: 14px; width: 180px; }

.keyword-actions { display: flex; justify-content: space-between; }

.btn-primary { background: #00539b; color: white; border: none; border-radius: 4px; padding: 8px 20px; cursor: pointer; font-size: 14px; }
.btn-primary:disabled { opacity: .5; cursor: not-allowed; }
.btn-secondary { background: white; color: #00539b; border: 1px solid #00539b; border-radius: 4px; padding: 8px 14px; cursor: pointer; font-size: 14px; }
```

- [ ] **Step 4: Verify in browser**

With both backend and `npm run dev` running, open `http://localhost:5173`. Should see the title, 3 keyword inputs, `+ Add Keyword` button, and `Search` button. Clicking Search with a keyword should trigger the API call (check browser network tab).

- [ ] **Step 5: Commit**

```bash
cd /Users/minkuanc/Claude/ieee-paper-search-web
git add frontend/src/
git commit -m "feat: KeywordInput component with search wiring"
```

---

## Task 8: `ResultsTable` Component

**Files:**
- Create: `frontend/src/components/ResultsTable.jsx`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/App.css`

- [ ] **Step 1: Create `ResultsTable.jsx`**

```jsx
export default function ResultsTable({ papers, truncated, total, selectedIndices, setSelectedIndices }) {
  if (papers.length === 0) return null

  function toggle(i) {
    setSelectedIndices(prev => {
      const next = new Set(prev)
      next.has(i) ? next.delete(i) : next.add(i)
      return next
    })
  }

  function selectAll() { setSelectedIndices(new Set(papers.map((_, i) => i))) }
  function deselectAll() { setSelectedIndices(new Set()) }

  return (
    <div className="results-section">
      {truncated && (
        <div className="truncation-banner">
          ⚠ Showing first 200 of {total.toLocaleString()} results — refine keywords for more.
        </div>
      )}
      <div className="results-controls">
        <span className="results-count">Found {papers.length} paper(s). {selectedIndices.size} selected.</span>
        <span>
          <button className="btn-secondary" onClick={selectAll}>Select All</button>{' '}
          <button className="btn-secondary" onClick={deselectAll}>Deselect All</button>
        </span>
      </div>
      <div className="table-wrap">
        <table className="results-table">
          <thead>
            <tr>
              <th style={{width:36}}>☐</th>
              <th>Title</th>
              <th style={{width:60}}>Year</th>
              <th style={{width:180}}>Authors</th>
              <th style={{width:160}}>Venue</th>
            </tr>
          </thead>
          <tbody>
            {papers.map((p, i) => (
              <tr key={i} onClick={() => toggle(i)} className={selectedIndices.has(i) ? 'selected' : ''}>
                <td style={{textAlign:'center'}}>{selectedIndices.has(i) ? '☑' : '☐'}</td>
                <td title={p.title}>{p.title.length > 80 ? p.title.slice(0,79) + '…' : p.title}</td>
                <td style={{textAlign:'center'}}>{p.year}</td>
                <td>{p.authors.length > 35 ? p.authors.slice(0,34) + '…' : p.authors}</td>
                <td>{p.venue.length > 35 ? p.venue.slice(0,34) + '…' : p.venue}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Add table styles to `App.css`**

```css
.results-section { background: white; border-radius: 8px; padding: 16px; margin-bottom: 16px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }

.truncation-banner { background: #fff9c4; border: 1px solid #f0c040; border-radius: 4px; padding: 8px 12px; margin-bottom: 12px; font-size: 13px; }

.results-controls { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }

.results-count { font-size: 13px; color: #555; }

.table-wrap { overflow-x: auto; max-height: 420px; overflow-y: auto; }

.results-table { width: 100%; border-collapse: collapse; font-size: 13px; }

.results-table th { background: #00539b; color: white; padding: 8px; text-align: left; position: sticky; top: 0; }

.results-table td { padding: 7px 8px; border-bottom: 1px solid #eee; cursor: pointer; }

.results-table tr:hover td { background: #f0f6ff; }
.results-table tr.selected td { background: #dceeff; }
```

- [ ] **Step 3: Add `ResultsTable` to `App.jsx`**

Add import and render it below `KeywordInput`:

```jsx
import ResultsTable from './components/ResultsTable'
// ...inside return:
<ResultsTable
  papers={papers}
  truncated={truncated}
  total={total}
  selectedIndices={selectedIndices}
  setSelectedIndices={setSelectedIndices}
/>
```

- [ ] **Step 4: Verify in browser**

Search for a keyword — table should populate with checkbox column, sortable visually by row click, Select All/Deselect All work, truncation banner appears for large result sets.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/
git commit -m "feat: ResultsTable with checkboxes and truncation banner"
```

---

## Task 9: `DownloadPanel` Component + SSE Progress

**Files:**
- Create: `frontend/src/components/DownloadPanel.jsx`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/App.css`

- [ ] **Step 1: Create `DownloadPanel.jsx`**

```jsx
import { useState } from 'react'

export default function DownloadPanel({ selectedPapers, keywords }) {
  const [destFolder, setDestFolder] = useState('')
  const [error, setError] = useState('')
  const [progress, setProgress] = useState(null)  // {index, total, title, done}
  const [jobId, setJobId] = useState(null)
  const [summary, setSummary] = useState(null)    // {downloaded, failed}
  const [downloading, setDownloading] = useState(false)

  async function handleDownload() {
    setError('')
    setSummary(null)
    setProgress(null)

    const res = await fetch('/api/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ papers: selectedPapers, dest_folder: destFolder, keywords }),
    })

    if (!res.ok) {
      const data = await res.json()
      setError(data.detail || 'Download failed')
      return
    }

    const { job_id } = await res.json()
    setJobId(job_id)
    setDownloading(true)

    const es = new EventSource(`/api/download/${job_id}/progress`)
    es.onmessage = e => {
      const event = JSON.parse(e.data)
      setProgress(event)
      if (event.done) {
        es.close()
        setDownloading(false)
        fetch(`/api/download/${job_id}/status`)
          .then(r => r.json())
          .then(s => setSummary(s))
      }
    }
    es.onerror = () => { es.close(); setDownloading(false) }
  }

  const canDownload = selectedPapers.length > 0 && destFolder.trim() && !downloading

  return (
    <div className="download-section">
      <div className="download-row">
        <input
          type="text"
          value={destFolder}
          onChange={e => setDestFolder(e.target.value)}
          placeholder="/Users/you/Downloads"
          className="folder-input"
        />
        <button onClick={handleDownload} disabled={!canDownload} className="btn-primary">
          {downloading ? 'Downloading…' : `Download Selected (${selectedPapers.length})`}
        </button>
      </div>

      {error && <div className="error-msg">⚠ {error}</div>}

      {progress && (
        <div className="progress-section">
          <progress value={progress.index} max={progress.total} className="progress-bar" />
          <div className="progress-label">
            {progress.index} / {progress.total} — {progress.title.slice(0, 60)}{progress.title.length > 60 ? '…' : ''}
          </div>
        </div>
      )}

      {summary && (
        <div className="summary">
          ✓ {summary.downloaded} downloaded, {summary.failed} failed.{' '}
          <a href={`/api/download/${jobId}/excel`} download="papers.xlsx" className="excel-link">
            Download Excel
          </a>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Add download styles to `App.css`**

```css
.download-section { background: white; border-radius: 8px; padding: 16px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }

.download-row { display: flex; gap: 8px; margin-bottom: 8px; }

.folder-input { flex: 1; border: 1px solid #ccc; border-radius: 4px; padding: 6px 10px; font-size: 14px; }

.error-msg { color: #c0392b; font-size: 13px; margin-top: 6px; }

.progress-section { margin-top: 10px; }

.progress-bar { width: 100%; height: 12px; border-radius: 6px; }

.progress-label { font-size: 12px; color: #555; margin-top: 4px; }

.summary { margin-top: 10px; font-size: 13px; color: #2d6a2d; }

.excel-link { color: #00539b; font-weight: bold; text-decoration: none; }
.excel-link:hover { text-decoration: underline; }
```

- [ ] **Step 3: Wire `DownloadPanel` into `App.jsx`**

Add import and state, then render below `ResultsTable`:

```jsx
import DownloadPanel from './components/DownloadPanel'
// inside return, after ResultsTable:
<DownloadPanel
  selectedPapers={papers.filter((_, i) => selectedIndices.has(i))}
  keywords={keywords}
/>
```

- [ ] **Step 4: Verify end-to-end in browser**

1. Start backend: `cd backend && uvicorn main:app --reload --port 8000`
2. Start frontend: `cd frontend && npm run dev`
3. Open `http://localhost:5173`
4. Search keywords → select papers → enter a valid local folder path → click Download
5. Progress bar should increment as Chrome downloads each paper
6. Summary + "Download Excel" link appear when done
7. Enter a non-existent path → error message shown inline

- [ ] **Step 5: Commit**

```bash
git add frontend/src/
git commit -m "feat: DownloadPanel with SSE progress and Excel download link"
```

---

## Task 10: Final Polish + README

**Files:**
- Create: `README.md`
- Create: `.gitignore`

- [ ] **Step 1: Create root `.gitignore`**

```
__pycache__/
*.pyc
.DS_Store
backend/.pytest_cache/
node_modules/
frontend/dist/
# ~/.ieee_search_app/ is outside the repo and cannot be gitignored here
```

- [ ] **Step 2: Create `README.md`**

```markdown
# IEEE Paper Search — Web App

A local web app to search IEEE Xplore for papers, browse results with checkboxes, and download PDFs organized by year.

## Prerequisites

- Python 3.9+
- Node.js 18+ (install from https://nodejs.org if not present)
- Google Chrome

## Setup

```bash
# Backend
cd backend && pip install -r requirements.txt

# Frontend
cd frontend && npm install
```

## Run

```bash
# Terminal 1 — backend
cd backend && uvicorn main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend && npm run dev
```

Open **http://localhost:5173**

## Features

- Enter 1–N keywords (3 by default), search IEEE Xplore (past 3 years)
- Results table sorted by year descending with per-row checkboxes
- PDFs saved to `<folder>/<keywords>/<year>/Full Title.pdf`
- `papers.xlsx` generated in the keyword root folder (deduped by DOI)
- Real-time SSE progress bar during download
- On first download, log into IEEE Xplore in the Chrome window that opens — session is saved automatically for future runs
```

- [ ] **Step 3: Final commit**

```bash
cd /Users/minkuanc/Claude/ieee-paper-search-web
git add README.md .gitignore
git commit -m "docs: add README and gitignore"
```

---

## Verification Checklist

Run through these after all tasks are complete:

- [ ] `pip install -r backend/requirements.txt` — no errors
- [ ] `npm install` in `frontend/` — no errors
- [ ] `python -m pytest backend/tests/ -v` — all tests pass
- [ ] Both servers start on ports 8000 and 5173
- [ ] `http://localhost:5173` loads with 3 keyword inputs
- [ ] Search returns results sorted by year descending
- [ ] Truncation banner shows when >200 total results
- [ ] `+ Add Keyword` adds a new input field
- [ ] Invalid folder path → inline error, no Chrome opened
- [ ] Valid folder path + checked papers → Chrome opens, progress bar increments
- [ ] PDFs appear in `<folder>/<keywords>/<year>/Full Title.pdf`
- [ ] `papers.xlsx` created with correct columns
- [ ] "Download Excel" link downloads the file
- [ ] Re-running same download → no duplicate rows in Excel

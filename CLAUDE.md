# IEEE Paper Search Web App — Claude Project Guide

## Project Overview
A local web application that searches IEEE Xplore by keywords, displays results in a sortable table with IEEE keyword data, lets the user select papers, and downloads their PDFs (using institutional network access) to a folder of their choice, with a live progress bar and Excel export.

**Stack:** FastAPI (Python) backend + React/Vite frontend, both running locally.

---

## Repository Layout

```
ieee-paper-search-web/
├── backend/
│   ├── main.py            # FastAPI app — all API routes
│   ├── scraper.py         # IEEE Xplore search + PDF download logic
│   ├── excel_writer.py    # openpyxl wrapper for papers.xlsx output
│   ├── requirements.txt   # Python dependencies
│   └── tests/
│       └── test_api.py    # pytest API tests (uses httpx TestClient)
├── frontend/
│   ├── vite.config.js     # Vite config — MUST proxy /api to 127.0.0.1:8000
│   ├── index.html
│   └── src/
│       ├── App.jsx            # Root component — state, search handler
│       ├── App.css
│       ├── components/
│       │   ├── KeywordInput.jsx   # Keyword chips + Search button
│       │   ├── ResultsTable.jsx   # Sortable table with stats bar
│       │   └── DownloadPanel.jsx  # Folder picker → download → SSE progress
│       └── main.jsx
├── install.sh             # One-command setup script for a new Mac
├── start.sh               # Starts backend (uvicorn) + frontend (vite)
├── .gitignore
└── README.md
```

---

## Running the App (Development)

### Start both servers (recommended)
```bash
bash start.sh
```
Then open **http://localhost:5173** (Vite may use 5174 if 5173 is occupied — check terminal output).

### Start servers individually
```bash
# Terminal 1 — Backend (port 8000)
cd backend
source venv/bin/activate      # or: conda activate your-env
uvicorn main:app --port 8000 --reload

# Terminal 2 — Frontend (port 5173)
cd frontend
npm run dev
```

### Run backend tests
```bash
cd backend
source venv/bin/activate
pytest tests/ -v
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/health` | Liveness check → `{"status":"ok"}` |
| `GET`  | `/api/choose-folder` | Opens macOS folder picker (tkinter subprocess); returns `{"path":"..."}` or `{"path":null,"cancelled":true}` |
| `POST` | `/api/search` | Search IEEE Xplore. Body: `{"keywords":["URLLC","MIMO"],"years_back":3}`. Returns `{"papers":[...],"truncated":bool,"total":int}` |
| `POST` | `/api/download` | Start download job. Body: `{"papers":[...],"dest_folder":"...","keywords":[...]}`. Returns `{"job_id":"..."}` |
| `GET`  | `/api/download/{job_id}/progress` | SSE stream of download progress events |
| `GET`  | `/api/download/{job_id}/status` | Final summary: `{"downloaded":N,"failed":N,"done":bool}` |
| `GET`  | `/api/download/{job_id}/excel` | Download the `papers.xlsx` file for this job |

### SSE Event format (`/progress`)
Each event is JSON on the `data:` field:
```json
{"index": 3, "total": 10, "title": "Paper Title", "status": "Downloaded", "local_path": "/path/file.pdf", "done": false}
```
The final event has `"done": true`. Clients can reconnect using `Last-Event-ID` for replay.

---

## Scraper Logic (`scraper.py`)

### Search flow (`search_papers`)
1. **Field-scoped IEEE query** — every keyword must match `"Document Title"` OR `"Author Keywords"` using IEEE's internal REST API (`/rest/search`). This keeps results tight.
2. **Parallel keyword fetch** — for each paper returned, fetches full IEEE Keywords + Author Keywords + Index Terms from `/rest/document/{articleNumber}/keywords` using a `ThreadPoolExecutor` with 10 workers.
3. **Post-filter verification** — keeps a paper only if every input keyword appears (case-insensitive substring) in the title or the fetched keyword list. This is the second pass that catches edge cases.
4. Returns `(papers, truncated, total)`. `total` is IEEE's full result count; `papers` is the verified subset (capped at 200).

### PDF Download flow (`PDFDownloader`)
Uses `undetected-chromedriver` with a **persistent Chrome profile** at `~/.ieee_search_app/chrome_profile` so institutional session cookies are reused between runs.

1. Navigate to the paper's IEEE page.
2. Find the PDF button link (tries 4 CSS selectors, falls back to `pdfLink` field from search).
3. Navigate to the stamp.jsp viewer URL.
4. Extract the actual `.pdf` URL from the `<iframe src>` on the viewer page.
5. Download the PDF using `requests` with the browser's current cookies.
6. Save to `<dest_folder>/<keywords>/<year>/<paper_title>.pdf`.

**First-run note:** Chrome opens in headed mode so the user can log in if IEEE prompts. After login the session is saved and subsequent runs are fully automatic.

---

## Key Technical Decisions

### Vite proxy — MUST use `127.0.0.1` not `localhost`
```js
// vite.config.js
proxy: { '/api': 'http://127.0.0.1:8000' }
```
On macOS, `localhost` resolves to IPv6 (`::1`) but uvicorn binds to IPv4 (`127.0.0.1`). Using `localhost` causes `ERR_CONNECTION_REFUSED` on every API call.

### Folder picker — subprocess, not in-process tkinter
tkinter must run on the main thread. FastAPI runs route handlers on worker threads, so calling tkinter directly crashes. The fix: spawn a `subprocess.run([sys.executable, "-c", tkinter_script])` which gets its own main thread.

### SSE replay on reconnect
The progress endpoint takes an atomic snapshot of `job["results"]` before entering the live-stream loop. This ensures `live_idx` (the index for new events) is exactly `len(buffered)`, preventing index gaps or double-delivery on client reconnect via `Last-Event-ID`.

### Async + threading bridge
PDF downloads are synchronous (Selenium + requests). They run in a `threading.Thread`. Progress events are pushed into an `asyncio.Queue` using `loop.call_soon_threadsafe(queue.put_nowait, event)`, where `loop` is captured with `asyncio.get_running_loop()` inside the async route handler before spawning the thread.

### Job store TTL cleanup
Jobs (in-memory dict) are cleaned up by a background `asyncio.create_task` that runs every 5 minutes and deletes entries older than 1 hour.

---

## Paper Data Schema

Each paper dict (from search or passed to download):

| Field | Type | Description |
|-------|------|-------------|
| `title` | str | Full paper title |
| `year` | int | Publication year |
| `authors` | str | Comma-separated author names |
| `venue` | str | Journal or conference name |
| `doi` | str | DOI string (may be empty) |
| `url` | str | IEEE Xplore paper page URL |
| `pdf_link` | str | IEEE PDF path (used as fallback) |
| `ieee_keywords` | list[str] | Keywords from IEEE, author, and index terms combined |

---

## Common Issues & Fixes

| Symptom | Cause | Fix |
|---------|-------|-----|
| Search returns nothing / connection refused | Vite proxy using `localhost` (IPv6) while uvicorn is IPv4 | `vite.config.js`: use `http://127.0.0.1:8000` |
| Folder picker does nothing / crashes backend | tkinter called on non-main thread | Already fixed: uses `subprocess.run` |
| Chrome crashes mid-download | Stale `SingletonLock` in profile dir | Already fixed: `_ensure_driver` removes lock files before launch |
| IEEE returns 418 / empty body | WAF rate-limit | Wait 30–60 seconds and retry |
| `ieee_keywords` column empty | Search API doesn't return keywords | Already fixed: parallel per-document keyword fetch |
| Vite starts on 5174 instead of 5173 | Port 5173 occupied by previous run | Normal — open whichever port Vite prints |

---

## Dependencies

### Python (`backend/requirements.txt`)
- `fastapi` — web framework
- `uvicorn[standard]` — ASGI server
- `requests` — IEEE REST API + PDF download
- `undetected-chromedriver` — Selenium with WAF bypass for PDF access
- `openpyxl` — Excel file generation
- `pytest` + `httpx` — testing

### Node (`frontend/package.json`)
- `react` + `react-dom`
- `vite` + `@vitejs/plugin-react`

---

## Installing on a New Mac

```bash
git clone https://github.com/minkuanc/ieee-paper-search-web.git
cd ieee-paper-search-web
bash install.sh   # one-time setup (~2 min)
bash start.sh     # start the app
# Open http://localhost:5173
```

Prerequisites: Python 3.10+, Node.js LTS, Google Chrome. Must be on institution network or VPN for PDF downloads.

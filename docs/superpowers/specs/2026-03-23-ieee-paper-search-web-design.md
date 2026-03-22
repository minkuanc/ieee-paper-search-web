# IEEE Paper Search — Web App Design Spec

**Date:** 2026-03-23
**Status:** Approved

---

## Context

The existing desktop app (`ieee-paper-search`) searches IEEE Xplore, lists papers, and downloads PDFs via a Python/Tkinter GUI. This project rebuilds it as a local web app with the same feature set: a FastAPI backend reusing the existing scraper/Excel logic, and a React (Vite) frontend served on localhost.

---

## Goals

- Search IEEE Xplore with 1–N keywords (3 by default), filtered to the past 3 years
- Display results in a table sorted by year descending with per-row checkboxes
- Download selected PDFs into `<dest>/<keywords>/<year>/Full Title.pdf` on the local machine
- Generate `papers.xlsx` in the root keyword folder, deduped by DOI
- Real-time per-paper progress updates in the browser during download

## Non-Goals

- No user authentication
- No cloud/remote deployment (localhost only)
- No persistent job history across server restarts

---

## Tech Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.9+, FastAPI, uvicorn |
| Search | `requests` (existing `scraper.py`, unchanged) |
| PDF download | `undetected-chromedriver` (existing `PDFDownloader`, unchanged) |
| Excel | `openpyxl` (existing `ExcelWriter`, unchanged) |
| Progress streaming | Server-Sent Events (SSE) via FastAPI `StreamingResponse` + `asyncio.Queue` |
| Frontend | React 18 + Vite |
| Styling | Plain CSS (no framework) |

---

## Project Structure

```
ieee-paper-search-web/
├── backend/
│   ├── main.py             # FastAPI app and all API routes
│   ├── scraper.py          # Copied from desktop app — unchanged
│   ├── excel_writer.py     # Copied from desktop app — unchanged
│   └── requirements.txt    # fastapi, uvicorn, requests, undetected-chromedriver, openpyxl
└── frontend/
    ├── src/
    │   ├── main.jsx
    │   ├── App.jsx
    │   ├── App.css
    │   └── components/
    │       ├── KeywordInput.jsx
    │       ├── ResultsTable.jsx   # shows truncation banner if truncated=true
    │       └── DownloadPanel.jsx
    ├── index.html
    └── package.json        # react, react-dom, vite
```

---

## API Design (`backend/main.py`)

### `POST /api/search`

**Request body:**
```json
{ "keywords": ["transformer", "image classification"], "years_back": 3 }
```

**Response** (backend guarantees `papers` is sorted year-descending):
```json
{
  "papers": [
    { "title": "...", "year": 2024, "authors": "...", "venue": "...", "doi": "...", "url": "...", "pdf_link": "..." }
  ],
  "total": 11521,
  "truncated": true
}
```

Calls `search_papers(keywords, years_back)` from `scraper.py`. Returns up to 200 results in year-descending order (guaranteed by the backend).

---

### `POST /api/download`

**Request body:**
```json
{
  "papers": [ { ...paper dict... } ],
  "dest_folder": "/Users/minkuanc/Downloads",
  "keywords": ["transformer", "image classification"]
}
```

**Validation (before starting job):**
- If `dest_folder` does not exist → return HTTP 400: `{"detail": "Destination folder does not exist"}`
- If `dest_folder` is not writable → return HTTP 400: `{"detail": "Destination folder is not writable"}`

**Response:**
```json
{ "job_id": "abc123" }
```

- Constructs root folder: `<dest_folder>/<keyword1_keyword2_...>/`
- Creates `os.makedirs(root, exist_ok=True)`
- Creates job state in an in-memory dict keyed by `job_id` (UUID):
  ```python
  jobs[job_id] = {
      "papers": [...],
      "root": "/path/to/root",
      "results": [],           # all completed events buffered here for replay
      "queue": asyncio.Queue(),
      "done": False,
      "created_at": time.time()
  }
  ```
- Starts a `threading.Thread` for `PDFDownloader`. The thread pushes events using:
  ```python
  loop.call_soon_threadsafe(queue.put_nowait, event_dict)
  ```
  where `loop` is the running asyncio event loop captured at request time via `asyncio.get_event_loop()`.
- A periodic cleanup task (`@app.on_event("startup")`) removes jobs older than 1 hour to prevent unbounded memory growth.

---

### `GET /api/download/{job_id}/progress`

**Response:** `text/event-stream` (SSE)

The generator is `async def`, using `await queue.get()` — it never blocks the event loop.

**Reconnect / replay support via `Last-Event-ID`:**
- Each event has an `id` field equal to its 0-based index.
- On reconnect, the browser sends `Last-Event-ID: N`. The server replays all buffered `results[N+1:]` before resuming live events from the queue.

**Event shape:**
```
id: 0
data: {"index": 1, "total": 5, "title": "Deep Learning...", "status": "Downloaded", "done": false}

id: 4
data: {"index": 5, "total": 5, "title": "Last paper", "status": "Downloaded", "done": true}
```

Frontend closes the `EventSource` on `done=true` (does not rely on auto-reconnect after completion).

---

### `GET /api/download/{job_id}/excel`

Streams `papers.xlsx` as a file download attachment once the job is done (`done=true`). Returns 404 if job not found, 425 if job not yet finished.

---

### `GET /api/download/{job_id}/status`

Returns final job summary:
```json
{ "downloaded": 4, "failed": 1, "root_folder": "/path/...", "done": true }
```

---

## CORS

```python
allow_origins=["*"]  # Safe: localhost-only deployment
```

This covers both the Vite dev server (port 5173) and Vite preview (port 4173).

---

## Frontend Design

### `KeywordInput.jsx`

- 3 `<input>` fields by default, in a flex row
- `+ Add Keyword` button appends a new input
- `Search` button calls `POST /api/search` with current non-empty keywords
- While loading: button shows "Searching…" and is disabled

### `ResultsTable.jsx`

- `<table>` with columns: ☐, Title, Year, Authors, Venue
- Clicking any row (or checkbox cell) toggles its checked state (stored as a `Set` of paper indices in React state passed up to `App`)
- `Select All` / `Deselect All` buttons
- Status line below table: `"Found N papers. M selected."`
- **Truncation banner:** if `truncated === true`, renders a yellow warning above the table: `"Showing first 200 of {total} results — refine keywords for more."`

### `DownloadPanel.jsx`

- Text `<input>` for destination folder path (user types the path)
- `Download Selected` button — on click:
  1. Calls `POST /api/download`; on 400 error, shows the error message inline
  2. Opens `EventSource` to `/api/download/{job_id}/progress`
  3. On each event: updates progress bar and status text
  4. On `done=true`: closes `EventSource`, shows summary, renders "Download Excel" link → `GET /api/download/{job_id}/excel`
- Progress: `<progress value={index} max={total}>` + status text `"N / total — current title"`

### `App.jsx`

Owns `papers`, `truncated`, `total`, `selectedIndices` state. Passes `papers` + `truncated` + `total` to `ResultsTable`, `selectedIndices` + setter to `ResultsTable`, and selected papers to `DownloadPanel`.

---

## Data Flow

```
User types keywords → Search → POST /api/search
                             ← { papers[], truncated, total }
                             → ResultsTable renders; truncation banner if needed

User checks papers  → Download → POST /api/download → { job_id }
                              → EventSource /progress/{job_id}
                                   per-paper SSE events → progress bar
                                   done=true → Download Excel link appears
```

---

## How to Run

```bash
# Backend
cd backend && pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend && npm install && npm run dev
# → open http://localhost:5173
```

---

## Verification

1. `pip install -r backend/requirements.txt` and `npm install` in `frontend/` complete without errors
2. Both servers start (`uvicorn` on 8000, Vite on 5173)
3. Open `http://localhost:5173` — 3 keyword inputs visible
4. Enter keywords → Search → results table populates sorted by year descending
5. Truncation banner appears if >200 total results
6. `+ Add Keyword` adds a 4th input
7. Enter a non-existent path → Download → error message shown inline (no Chrome opened)
8. Enter a valid path → Download → Chrome opens on the machine, progress bar increments per paper
9. PDFs saved to `<dest>/<keywords>/<year>/Full Title.pdf`
10. `papers.xlsx` created in `<dest>/<keywords>/` with correct columns and data
11. "Download Excel" link appears after completion; clicking it downloads the file to the browser
12. Re-running download for same papers → no duplicate rows in Excel (DOI dedup)
13. Leaving the server running and running multiple searches → no memory leak (old jobs cleaned up after 1 hour)

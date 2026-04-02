import asyncio
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import asynccontextmanager

import json

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from scraper import search_papers, PDFDownloader
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


class SearchRequest(BaseModel):
    keywords: list[str]
    start_year: int = 0  # 0 = default (current year - 3)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/choose-folder")
def choose_folder():
    """Open a native macOS folder picker.
    Tkinter must run on the main thread; we spawn a subprocess so it gets one.
    Returns {"path": "<folder>"} or {"path": null, "cancelled": true}.
    """
    import subprocess, sys
    script = (
        "import tkinter as tk\n"
        "from tkinter import filedialog\n"
        "root = tk.Tk()\n"
        "root.withdraw()\n"
        "root.wm_attributes('-topmost', 1)\n"
        "folder = filedialog.askdirectory(title='Select destination folder')\n"
        "root.destroy()\n"
        "print(folder)\n"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=120,
        )
        folder = result.stdout.strip()
    except subprocess.TimeoutExpired:
        folder = ""
    if not folder:
        return {"path": None, "cancelled": True}
    return {"path": folder}


@app.post("/api/search")
def api_search(req: SearchRequest):
    kws = [k.strip() for k in req.keywords if k.strip()]
    if not kws:
        raise HTTPException(status_code=400, detail="At least one keyword is required")
    papers, truncated, total = search_papers(kws, req.start_year)
    return {"papers": papers, "truncated": truncated, "total": total}


class PaperItem(BaseModel):
    title: str
    year: int
    authors: str
    venue: str
    doi: str
    url: str
    pdf_link: str = ""
    ieee_keywords: list[str] = []
    abstract: str = ""


class DownloadRequest(BaseModel):
    papers: list[PaperItem]
    dest_folder: str
    keywords: list[str]


def _sanitize_folder_name(kw: str) -> str:
    return re.sub(r'[\\/:*?"<>| ]', "_", kw)


def _run_download(job_id: str, loop: asyncio.AbstractEventLoop):
    """
    Background thread: download papers in parallel and push SSE progress events.

    Strategy:
      1. Use the browser once to establish an IEEE session and grab cookies.
      2. Attempt each PDF via a direct requests download (fast, parallelisable).
      3. Any paper whose direct download fails falls back to the full browser
         navigation path (serialised with a lock to avoid Selenium conflicts).
    """
    job = jobs[job_id]
    downloader = PDFDownloader()
    papers = job["papers"]
    total = len(papers)
    results_lock = threading.Lock()
    browser_lock = threading.Lock()   # serialise Selenium fallback calls

    try:
        # ── Step 1: one browser visit to get session cookies ─────────────────
        cookies, ua = downloader.prepare_session()

        # ── Step 2: parallel downloads ────────────────────────────────────────
        def _download_one(idx_paper):
            idx, paper = idx_paper
            # Fast path: direct HTTP download using session cookies
            local_path, status = downloader.download_direct(
                paper, job["root"], cookies, ua
            )
            # Slow path: full browser navigation (serialised)
            if not local_path:
                with browser_lock:
                    local_path, status = downloader.download(paper, job["root"])

            event = {
                "index": idx + 1,
                "total": total,
                "title": paper["title"],
                "status": status,
                "local_path": local_path,
                "done": False,
            }
            with results_lock:
                job["results"].append(event)
            loop.call_soon_threadsafe(job["queue"].put_nowait, event)

        with ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(_download_one, enumerate(papers)))

        # ── Step 3: write Excel (sort results back into paper order) ──────────
        job["results"].sort(key=lambda e: e["index"])
        excel_path = os.path.join(job["root"], "papers.xlsx")
        writer = ExcelWriter(excel_path)
        writer.append_papers([
            {**papers[e["index"] - 1], "local_path": e["local_path"], "status": e["status"]}
            for e in job["results"]
        ])
        writer.save()
        job["excel_path"] = excel_path

        terminal_event = {
            "index": total, "total": total,
            "title": "", "status": "Done", "local_path": "", "done": True,
        }
        job["results"].append(terminal_event)
        loop.call_soon_threadsafe(job["queue"].put_nowait, terminal_event)
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
    if not root_name:
        raise HTTPException(status_code=400, detail="At least one keyword is required")
    root = os.path.join(req.dest_folder, root_name)
    os.makedirs(root, exist_ok=True)

    job_id = str(uuid.uuid4())
    loop = asyncio.get_running_loop()
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


@app.get("/api/download/{job_id}/progress")
async def api_progress(job_id: str, request: Request):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]
    last_event_id = request.headers.get("last-event-id") or request.headers.get("Last-Event-ID")
    replay_from = int(last_event_id) + 1 if last_event_id and last_event_id.isdigit() else 0

    async def event_stream():
        # Snapshot results to get a consistent replay slice and live_idx
        buffered = list(job["results"])
        live_idx = len(buffered)
        # Replay buffered events on reconnect
        for i, event in enumerate(buffered[replay_from:], start=replay_from):
            yield f"id: {i}\ndata: {json.dumps(event)}\n\n"
            if event.get("done"):
                return
        # Stream live events
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
    failed = sum(1 for r in job["results"] if r["status"] not in ("Downloaded", "Done"))
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

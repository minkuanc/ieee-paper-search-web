import asyncio
import os
import re
import threading
import time
import uuid
import queue as _queue
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
    content_type: str = ""


class DownloadRequest(BaseModel):
    papers: list[PaperItem]
    dest_folder: str
    keywords: list[str]


def _sanitize_folder_name(kw: str) -> str:
    return re.sub(r'[\\/:*?"<>| ]', "_", kw)


def _run_download(job_id: str, loop: asyncio.AbstractEventLoop):
    """
    Producer-consumer pipeline for parallel PDF downloads.

    One browser thread (producer) navigates IEEE sequentially to extract the
    actual PDF CDN URL for each paper, then 10 download threads (consumers)
    save the files in parallel via requests — fully overlapping with browser
    navigation for the next paper.

    Stop works by setting job["stop_requested"] = True:
      - The producer skips browser navigation and emits "Stopped" tokens.
      - Consumer threads skip the requests download for those tokens.
      - Papers already in-flight finish; no new ones start.
    """
    job = jobs[job_id]
    downloader = PDFDownloader()
    papers = job["papers"]
    total = len(papers)
    results_lock = threading.Lock()
    N_WORKERS = 10

    # url_queue items: (idx, paper, pdf_url, cookies, ua)
    # None = sentinel (one per worker thread)
    url_queue: _queue.Queue = _queue.Queue(maxsize=N_WORKERS * 2)

    try:
        def browser_producer():
            """Runs in its own thread; owns the Selenium driver."""
            try:
                for idx, paper in enumerate(papers):
                    if job["stop_requested"]:
                        # Drain remaining with empty URL so workers emit Stopped
                        for rem_idx, rem_paper in [(idx, paper)] + list(enumerate(papers[idx + 1:], start=idx + 1)):
                            url_queue.put((rem_idx, rem_paper, "", {}, ""))
                        return
                    pdf_url, cookies, ua = downloader.get_pdf_url(paper)
                    url_queue.put((idx, paper, pdf_url, cookies, ua))
            except Exception as exc:
                print(f"[producer] unexpected error: {exc}")
            finally:
                for _ in range(N_WORKERS):
                    url_queue.put(None)  # sentinel per worker

        def download_worker():
            """Runs in thread pool; calls save_pdf (thread-safe)."""
            while True:
                item = url_queue.get()
                if item is None:
                    break
                idx, paper, pdf_url, cookies, ua = item

                if job["stop_requested"] or not pdf_url:
                    status = "Stopped" if job["stop_requested"] else f"No PDF URL: {ua}"
                    local_path = ""
                else:
                    local_path, status = PDFDownloader.save_pdf(
                        pdf_url, paper, job["root"], cookies, ua
                    )

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

        # Start browser producer in its own thread
        producer_thread = threading.Thread(target=browser_producer, daemon=True)
        producer_thread.start()

        # Run download workers in thread pool
        with ThreadPoolExecutor(max_workers=N_WORKERS) as pool:
            futures = [pool.submit(download_worker) for _ in range(N_WORKERS)]
            for f in futures:
                f.result()

        producer_thread.join(timeout=10)

        # Write Excel (sort by paper index to preserve original order)
        job["results"].sort(key=lambda e: e["index"])
        excel_path = os.path.join(job["root"], "papers.xlsx")
        writer = ExcelWriter(excel_path)
        writer.append_papers([
            {**papers[e["index"] - 1], "local_path": e["local_path"], "status": e["status"]}
            for e in job["results"]
            if not e.get("done")
        ])
        writer.save()
        job["excel_path"] = excel_path

        stopped = job["stop_requested"]
        terminal_event = {
            "index": total, "total": total,
            "title": "", "status": "Stopped" if stopped else "Done",
            "local_path": "", "done": True,
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
        "stop_requested": False,
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


@app.post("/api/download/{job_id}/stop")
def api_stop(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    jobs[job_id]["stop_requested"] = True
    return {"ok": True}


@app.get("/api/download/{job_id}/status")
def api_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    downloaded = sum(1 for r in job["results"] if r["status"] == "Downloaded")
    failed = sum(1 for r in job["results"] if r["status"] not in ("Downloaded", "Stopped", "Done"))
    stopped = job.get("stop_requested", False)
    return {
        "downloaded": downloaded,
        "failed": failed,
        "stopped": stopped,
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

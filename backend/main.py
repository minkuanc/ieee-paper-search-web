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
    Multi-browser producer-consumer pipeline for parallel PDF downloads.

    Architecture:
      N_BROWSERS Chrome instances each pick papers from a shared paper_queue,
      navigate to extract the real PDF CDN URL, then put the result into
      url_queue.  N_DOWNLOADERS worker threads consume url_queue and save
      files via requests — all in parallel.

      Timeline (N_BROWSERS=3, N_DOWNLOADERS=10):
        t=0   browsers 0,1,2 start navigating papers 0,1,2
        t=5s  each browser gets PDF URL → download workers start saving
              browser immediately picks next paper (0→3, 1→4, 2→5)
        → 3 papers navigating + up to 10 downloading simultaneously

    Stop:
      browser_producer checks stop_requested before each paper;
      skips browser navigation and emits empty-URL tokens that workers
      convert to "Stopped" events instantly.
    """
    job = jobs[job_id]
    papers = job["papers"]
    total = len(papers)
    results_lock = threading.Lock()

    N_BROWSERS    = 3   # parallel Chrome windows
    N_DOWNLOADERS = 10  # parallel requests download threads

    # paper_queue: (idx, paper) tuples consumed by browser threads
    paper_queue: _queue.Queue = _queue.Queue()
    for idx, paper in enumerate(papers):
        paper_queue.put((idx, paper))

    # url_queue: (idx, paper, pdf_url, cookies, ua) consumed by download workers
    url_queue: _queue.Queue = _queue.Queue(maxsize=N_DOWNLOADERS * 2)

    # Keep refs so we can close browsers in finally
    downloaders: list[PDFDownloader] = []
    downloaders_lock = threading.Lock()

    try:
        def browser_producer(browser_id: int):
            profile_dir = os.path.join(
                os.path.expanduser("~"), ".ieee_search_app",
                f"chrome_profile_{browser_id}"
            )
            dl = PDFDownloader(user_data_dir=profile_dir)
            with downloaders_lock:
                downloaders.append(dl)
            try:
                while True:
                    try:
                        idx, paper = paper_queue.get_nowait()
                    except _queue.Empty:
                        break
                    if job["stop_requested"]:
                        url_queue.put((idx, paper, "", {}, "Stopped"))
                        # Drain the rest of the paper_queue
                        while True:
                            try:
                                rem_idx, rem_paper = paper_queue.get_nowait()
                                url_queue.put((rem_idx, rem_paper, "", {}, "Stopped"))
                            except _queue.Empty:
                                break
                        break
                    pdf_url, cookies, ua = dl.get_pdf_url(paper)
                    url_queue.put((idx, paper, pdf_url, cookies, ua))
            except Exception as exc:
                print(f"[browser {browser_id}] error: {exc}")
            finally:
                dl.close()

        def download_worker():
            while True:
                item = url_queue.get()
                if item is None:
                    break
                idx, paper, pdf_url, cookies, ua = item

                if job["stop_requested"] or not pdf_url:
                    status = "Stopped"
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

        # Start N_BROWSERS browser threads
        browser_threads = [
            threading.Thread(target=browser_producer, args=(i,), daemon=True)
            for i in range(min(N_BROWSERS, total))
        ]
        for t in browser_threads:
            t.start()

        # When all browsers finish, send sentinels to download workers
        def _wait_then_signal():
            for t in browser_threads:
                t.join()
            for _ in range(N_DOWNLOADERS):
                url_queue.put(None)

        signal_thread = threading.Thread(target=_wait_then_signal, daemon=True)
        signal_thread.start()

        # Run download workers
        with ThreadPoolExecutor(max_workers=N_DOWNLOADERS) as pool:
            futures = [pool.submit(download_worker) for _ in range(N_DOWNLOADERS)]
            for f in futures:
                f.result()

        signal_thread.join(timeout=10)

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

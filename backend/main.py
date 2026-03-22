import asyncio
import os
import re
import threading
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
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
    years_back: int = 3


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/search")
def api_search(req: SearchRequest):
    kws = [k.strip() for k in req.keywords if k.strip()]
    if not kws:
        raise HTTPException(status_code=400, detail="At least one keyword is required")
    papers, truncated, total = search_papers(kws, req.years_back)
    return {"papers": papers, "truncated": truncated, "total": total}


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

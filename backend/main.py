import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from scraper import search_papers

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

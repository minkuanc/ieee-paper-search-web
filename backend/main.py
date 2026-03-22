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

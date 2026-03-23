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

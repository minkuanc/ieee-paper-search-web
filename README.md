# IEEE Paper Search

A local web app that searches IEEE Xplore by keyword, displays results in a sortable table, and downloads selected PDFs using your institution's access.

---

## Requirements (install these first)

| Software | Minimum version | Download |
|---|---|---|
| **Google Chrome** | Any recent version | https://www.google.com/chrome/ |
| **Python** | 3.10 or newer | https://www.python.org/downloads/ |
| **Node.js** | 18 or newer (LTS) | https://nodejs.org/ |

> **Note:** If your institution's IEEE access is IP-based (most universities), the app works automatically when your Mac is on the campus network or VPN. If IEEE requires a browser login, open the Chrome window that pops up during the first download and log in — subsequent runs will reuse that session.

---

## Installation (run once on a new Mac)

**Step 1 — Copy the project folder to the new Mac.**

Use AirDrop, a USB drive, or zip and email it. The folder is called `ieee-paper-search-web`.

**Step 2 — Open Terminal, navigate to the folder, and run:**

```bash
bash install.sh
```

This will:
- Check that Chrome, Python, and Node.js are installed
- Create a Python virtual environment inside `backend/venv/` and install all Python packages
- Install all Node.js packages inside `frontend/node_modules/`
- Pre-download the correct ChromeDriver for your Chrome version

Installation takes about 1–2 minutes.

---

## Starting the app

Every time you want to use the app, run:

```bash
bash start.sh
```

Then open **http://localhost:5173** in your browser.

Press **Ctrl+C** in Terminal to stop both servers when done.

---

## How to use

1. **Search** — Enter 1–5 keywords and click Search. Results show only papers where every keyword appears in the paper title or IEEE keywords. Searching takes 15–40 seconds depending on result count.

2. **Review results** — The table shows title, year, authors, venue, and IEEE keywords. The stats bar at the top tells you how many papers IEEE found in total vs. how many passed the keyword filter.

3. **Select papers** — Click rows to check/uncheck. Use Select All / Deselect All for bulk selection.

4. **Download** — Click **Download Selected (N)**. A folder picker dialog opens — choose where to save. A Chrome window will open and navigate to each paper to download the PDF using your institutional access. A progress bar tracks each download.

5. **Excel file** — After downloading, click **Download Excel** to get a `papers.xlsx` spreadsheet listing all papers with their download status and file paths.

---

## Project structure

```
ieee-paper-search-web/
├── install.sh              ← run once to set up on a new Mac
├── start.sh                ← run each time to start the app
├── backend/
│   ├── main.py             ← FastAPI server
│   ├── scraper.py          ← IEEE search + PDF downloader
│   ├── excel_writer.py     ← Excel export
│   └── requirements.txt    ← Python dependencies
└── frontend/
    ├── src/
    │   ├── App.jsx
    │   └── components/
    └── package.json        ← Node.js dependencies
```

---

## Troubleshooting

**"Cannot reach backend" error in the browser**
→ Make sure you ran `bash start.sh` and both servers started without errors.

**Chrome opens but PDFs don't download**
→ Your institution's access may require a browser login. In the Chrome window that opens during download, navigate to https://ieeexplore.ieee.org and log in via your institution. Close Chrome and try again — the session is saved for future runs.

**"IEEE Xplore blocked the request" during search**
→ The site is rate-limiting. Wait 30 seconds and try again.

**Search returns fewer results than expected**
→ By design: only papers where every keyword appears in the title or IEEE keyword list are shown. Try broader or fewer keywords.

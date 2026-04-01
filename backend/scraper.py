"""
IEEE Xplore scraper.

- search_papers(): uses requests against the internal /rest/search JSON API
- PDFDownloader: uses undetected-chromedriver with a persistent Chrome profile
  to download PDFs (inherits institutional access from the user's session).
"""

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import requests

SEARCH_URL = "https://ieeexplore.ieee.org/rest/search"
BASE_URL = "https://ieeexplore.ieee.org"
ROWS_PER_PAGE = 25
MAX_RESULTS = 200


def _sanitize_filename(title: str) -> str:
    """Convert a paper title to a safe filename, preserving the full title."""
    name = re.sub(r'[\\/:*?"<>|]', "_", title).strip()
    return name + ".pdf"


def _make_session() -> requests.Session:
    """
    Create a requests.Session pre-loaded with IEEE Xplore cookies.
    IEEE's WAF rejects requests that lack browser-like cookies, so we
    first do a GET on the homepage to pick them up.
    """
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }
    )
    try:
        session.get("https://ieeexplore.ieee.org/", timeout=15)
    except Exception:
        pass  # proceed even if the prefetch fails; cookies may still work
    return session


def _fetch_keywords(article_number: str | int, session: requests.Session) -> list[str]:
    """
    Fetch IEEE Keywords, Author Keywords, and Index Terms for a single paper
    from the per-document REST endpoint.  Returns a flat list of original-case
    strings, or [] on any error.
    """
    url = f"{BASE_URL}/rest/document/{article_number}/keywords"
    try:
        resp = session.get(
            url,
            headers={"Accept": "application/json",
                     "Referer": "https://ieeexplore.ieee.org/"},
            timeout=15,
        )
        if not resp.ok:
            return []
        data = resp.json()
    except Exception:
        return []

    kws: list[str] = []
    for group in data.get("keywords", []):
        for term in group.get("kwd", []):
            if isinstance(term, str) and term.strip():
                kws.append(term.strip())
    return kws


def _paper_matches(title: str, ieee_keywords: list[str], input_keywords: list[str]) -> bool:
    """
    Return True if every input keyword appears in the paper title OR in the
    fetched IEEE / author keyword list.  Matching is case-insensitive and
    substring-based ("MIMO" matches "Massive MIMO", etc.).
    """
    title_lower = title.lower()
    kw_blobs = [k.lower() for k in ieee_keywords]

    for kw in input_keywords:
        kw_lower = kw.strip().lower()
        if not kw_lower:
            continue
        if kw_lower in title_lower:
            continue
        if any(kw_lower in blob for blob in kw_blobs):
            continue
        return False
    return True


def search_papers(keywords: list[str], start_year: int = 0) -> list[dict]:
    """
    Search IEEE Xplore for papers where every keyword appears in either
    the paper title OR the IEEE/author keyword list.

    Strategy:
      1. Ask IEEE with a field-scoped query (Document Title + Author Keywords).
      2. Collect all matching records (up to MAX_RESULTS).
      3. Fetch the full keyword lists in parallel from the per-document endpoint.
      4. Post-filter using fetched keywords + title (second-pass verification).

    Returns (papers, truncated, total) where:
      - total      = totalRecords reported by IEEE for the scoped query
      - truncated  = True when the capped list < full IEEE result set
      - papers     = verified list with ieee_keywords populated, sorted by year
    """
    current_year = datetime.now().year
    if not start_year or start_year <= 0:
        start_year = current_year - 3
    year_range = f"{start_year}_{current_year}_Year"

    # Field-scoped query: every keyword must appear in title OR author keywords
    kw_clauses = []
    for kw in keywords:
        kw = kw.strip()
        if not kw:
            continue
        quoted = kw.replace('"', '')
        kw_clauses.append(
            f'(("Document Title":"{quoted}") OR ("Author Keywords":"{quoted}"))'
        )
    query_text = " AND ".join(kw_clauses) if kw_clauses else ""

    session = _make_session()
    search_headers = {
        "Content-Type": "application/json",
        "Referer": "https://ieeexplore.ieee.org/search/searchresult.html",
        "Origin": "https://ieeexplore.ieee.org",
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
    }

    # ── Step 1: collect raw records from paginated search ────────────────────
    raw_papers = []
    page = 1
    total = 0

    while True:
        payload = {
            "newsearch": True,
            "queryText": query_text,
            "ranges": [year_range],
            "pageNumber": page,
            "rowsPerPage": ROWS_PER_PAGE,
            "sortType": "newest",
        }

        try:
            resp = session.post(
                SEARCH_URL, json=payload, headers=search_headers, timeout=20
            )
            if resp.status_code == 418 or not resp.text.strip():
                raise RuntimeError(
                    "IEEE Xplore blocked the request (WAF). "
                    "Try again in a moment — the site may be rate-limiting."
                )
            resp.raise_for_status()
            data = resp.json()
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Search request failed: {exc}") from exc

        records = data.get("records", [])
        total = data.get("totalRecords", 0)

        for record in records:
            authors_list = record.get("authors", [])
            authors_str = ", ".join(
                a.get("normalizedName", a.get("preferredName", a.get("name", "")))
                for a in authors_list
            )
            doc_link = record.get("documentLink", "")
            url = BASE_URL + doc_link if doc_link.startswith("/") else doc_link

            raw_papers.append({
                "article_number": str(record.get("articleNumber", "")),
                "title": record.get("articleTitle", "Unknown Title"),
                "year": int(record.get("publicationYear", 0)),
                "authors": authors_str,
                "venue": record.get("publicationTitle", record.get("displayPublicationTitle", "")),
                "doi": record.get("doi", ""),
                "url": url,
                "pdf_link": record.get("pdfLink", ""),
            })

            if len(raw_papers) >= MAX_RESULTS:
                break

        if len(raw_papers) >= MAX_RESULTS or len(raw_papers) >= total or not records:
            break

        page += 1

    # ── Step 2: fetch full keyword lists in parallel ──────────────────────────
    kw_map: dict[str, list[str]] = {}   # article_number → keyword list

    def _fetch(art_num: str) -> tuple[str, list[str]]:
        return art_num, _fetch_keywords(art_num, session)

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_fetch, p["article_number"]): p["article_number"]
                   for p in raw_papers if p["article_number"]}
        for fut in as_completed(futures):
            art_num, kws = fut.result()
            kw_map[art_num] = kws

    # ── Step 3: post-filter and assemble final list ───────────────────────────
    papers = []
    for p in raw_papers:
        ieee_kws = kw_map.get(p["article_number"], [])
        # Keep paper only if every input keyword is in title OR fetched keywords
        if not _paper_matches(p["title"], ieee_kws, keywords):
            continue
        papers.append({
            "title": p["title"],
            "year": p["year"],
            "authors": p["authors"],
            "venue": p["venue"],
            "doi": p["doi"],
            "url": p["url"],
            "pdf_link": p["pdf_link"],
            "ieee_keywords": ieee_kws,
        })

    papers.sort(key=lambda p: p["year"], reverse=True)
    truncated = len(raw_papers) >= MAX_RESULTS and total > MAX_RESULTS
    return papers, truncated, total


class PDFDownloader:
    """
    Downloads IEEE paper PDFs using undetected-chromedriver with a persistent
    Chrome profile so institutional cookies are reused between runs.
    """

    def __init__(self, user_data_dir: str | None = None):
        self._driver = None
        self._user_data_dir = user_data_dir or str(
            Path.home() / ".ieee_search_app" / "chrome_profile"
        )

    @staticmethod
    def _chrome_major_version() -> int | None:
        """Return the installed Chrome major version number, or None if unknown."""
        import subprocess, re
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "google-chrome",
            "google-chrome-stable",
            "chromium-browser",
        ]
        for exe in candidates:
            try:
                out = subprocess.check_output([exe, "--version"],
                                              stderr=subprocess.DEVNULL, text=True)
                m = re.search(r"(\d+)\.\d+\.\d+", out)
                if m:
                    return int(m.group(1))
            except Exception:
                continue
        return None

    def _ensure_driver(self):
        if self._driver is not None:
            return
        import undetected_chromedriver as uc

        os.makedirs(self._user_data_dir, exist_ok=True)
        # Remove stale Chrome singleton locks left by previous crashes.
        # If these exist Chrome will refuse to start with this profile.
        for lock in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
            lock_path = os.path.join(self._user_data_dir, lock)
            try:
                os.remove(lock_path)
            except FileNotFoundError:
                pass
        options = uc.ChromeOptions()
        options.add_argument(f"--user-data-dir={self._user_data_dir}")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        # Detect Chrome version so uc downloads the matching chromedriver
        version_main = self._chrome_major_version()
        # non-headless so user can log in on first run
        self._driver = uc.Chrome(
            options=options,
            headless=False,
            **({"version_main": version_main} if version_main else {}),
        )

    def download(self, paper: dict, dest_folder: str) -> tuple[str, str]:
        """
        Download the PDF for `paper` into `<dest_folder>/<year>/`.

        Flow:
          1. Navigate to paper page; find and follow the PDF icon link
             (leads to /stamp/stamp.jsp viewer page)
          2. On the viewer page, extract the actual PDF URL from the <iframe>
          3. Download that URL via requests using the browser's session cookies

        Returns (local_path, status) where local_path is "" on failure.
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        # If the previous Chrome session died (e.g. user closed window), reset it.
        if self._driver is not None:
            try:
                _ = self._driver.current_url  # cheap liveness check
            except Exception:
                try:
                    self._driver.quit()
                except Exception:
                    pass
                self._driver = None

        self._ensure_driver()
        driver = self._driver

        year_folder = os.path.join(dest_folder, str(paper["year"]))
        os.makedirs(year_folder, exist_ok=True)

        # ── Step 1: Navigate to the paper page ───────────────────────────────
        try:
            driver.get(paper["url"])
            time.sleep(2)
        except Exception as exc:
            return ("", f"Navigation failed: {exc}")

        # ── Step 2: Find the PDF button URL ───────────────────────────────────
        stamp_url = None

        _pdf_selectors = [
            "a.stats-document-lh-action-downloadPdf_2",
            "a[href*='/stamp/stamp.jsp']",
            "a.btn-pdf",
            "a[href*='/pdf/']",
        ]
        for sel in _pdf_selectors:
            try:
                el = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, sel))
                )
                href = el.get_attribute("href")
                if href:
                    stamp_url = href
                    print(f"[PDFDownloader] PDF button found ({sel}): {href[:80]}")
                    break
            except Exception:
                continue

        # Fall back: build stamp URL from pdfLink field or article number in URL
        if not stamp_url:
            pdf_link_field = paper.get("pdf_link", "")
            if pdf_link_field:
                stamp_url = (
                    BASE_URL + pdf_link_field
                    if pdf_link_field.startswith("/")
                    else pdf_link_field
                )
            else:
                m = re.search(r"/document/(\d+)", paper["url"])
                if m:
                    stamp_url = (
                        f"https://ieeexplore.ieee.org/stamp/stamp.jsp"
                        f"?arnumber={m.group(1)}"
                    )

        if not stamp_url:
            print(f"[PDFDownloader] No PDF URL found for: {paper['title']!r}")
            return ("", "No PDF link found on paper page")

        # ── Step 3: Navigate to PDF viewer (stamp.jsp) ───────────────────────
        try:
            driver.get(stamp_url)
            time.sleep(3)
        except Exception as exc:
            return ("", f"PDF viewer navigation failed: {exc}")

        # ── Step 4: Extract actual PDF URL from iframe ────────────────────────
        actual_pdf_url = None

        # Try iframe src first
        for iframe_sel in ["iframe#pdf-viewer", "iframe[src*='.pdf']", "iframe[src*='iel']", "iframe"]:
            try:
                iframe = WebDriverWait(driver, 8).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, iframe_sel))
                )
                src = iframe.get_attribute("src")
                if src and src.startswith("http"):
                    actual_pdf_url = src
                    print(f"[PDFDownloader] PDF iframe src: {src[:80]}")
                    break
            except Exception:
                continue

        # If no iframe, the browser might have redirected to the raw PDF URL
        if not actual_pdf_url:
            current = driver.current_url
            if ".pdf" in current or "getPDF" in current or "ielx" in current:
                actual_pdf_url = current
                print(f"[PDFDownloader] PDF URL from redirect: {current[:80]}")

        if not actual_pdf_url:
            return ("", "Access denied or paywall — PDF viewer did not load")

        # ── Step 5: Download using requests + browser session cookies ─────────
        cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
        ua = driver.execute_script("return navigator.userAgent;")
        dl_headers = {
            "User-Agent": ua,
            "Referer": stamp_url,
            "Accept": "application/pdf,*/*",
        }

        try:
            resp = requests.get(
                actual_pdf_url,
                cookies=cookies,
                headers=dl_headers,
                timeout=60,
                stream=True,
            )
            content_type = resp.headers.get("content-type", "")
            if resp.status_code == 200 and "pdf" in content_type.lower():
                filename = _sanitize_filename(paper["title"])
                filepath = os.path.join(year_folder, filename)
                with open(filepath, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                print(f"[PDFDownloader] Saved: {filepath}")
                return (filepath, "Downloaded")
            else:
                return (
                    "",
                    f"Download failed: HTTP {resp.status_code}, "
                    f"content-type={content_type!r}",
                )
        except Exception as exc:
            return ("", f"Download request failed: {exc}")

    def close(self):
        if self._driver is not None:
            try:
                self._driver.quit()
            except Exception:
                pass
            self._driver = None

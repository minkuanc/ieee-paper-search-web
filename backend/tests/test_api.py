import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}

def test_cors_header():
    r = client.options(
        "/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert r.headers.get("access-control-allow-origin") == "*"

def test_search_returns_papers():
    fake_papers = [
        {"title": "Paper A", "year": 2024, "authors": "Smith", "venue": "IEEE", "doi": "10.1/a", "url": "http://x", "pdf_link": "/a"}
    ]
    with patch("main.search_papers", return_value=(fake_papers, False, 1)):
        r = client.post("/api/search", json={"keywords": ["deep learning"], "years_back": 3})
    assert r.status_code == 200
    data = r.json()
    assert len(data["papers"]) == 1
    assert data["truncated"] is False
    assert data["total"] == 1

def test_search_empty_keywords_returns_400():
    r = client.post("/api/search", json={"keywords": [], "years_back": 3})
    assert r.status_code == 400

def test_download_nonexistent_folder_returns_400():
    r = client.post("/api/download", json={
        "papers": [{"title": "P", "year": 2024, "authors": "", "venue": "", "doi": "x", "url": "http://x", "pdf_link": ""}],
        "dest_folder": "/nonexistent/path/xyz",
        "keywords": ["deep learning"]
    })
    assert r.status_code == 400
    assert "does not exist" in r.json()["detail"]

def test_download_valid_folder_returns_job_id():
    with tempfile.TemporaryDirectory() as tmp:
        with patch("main.threading.Thread"):  # don't actually start download
            r = client.post("/api/download", json={
                "papers": [{"title": "P", "year": 2024, "authors": "", "venue": "", "doi": "x", "url": "http://x", "pdf_link": ""}],
                "dest_folder": tmp,
                "keywords": ["deep learning"]
            })
    assert r.status_code == 200
    assert "job_id" in r.json()

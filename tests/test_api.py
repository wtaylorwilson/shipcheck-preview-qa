from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

# Inline worker off so POST only queues; tests do not launch Chromium.
os.environ["SHIPCHECK_INLINE_WORKER"] = "0"
os.environ.setdefault("SHIPCHECK_HOME", "/workspace/shipcheck")

from shipcheck.server import app  # noqa: E402
from shipcheck.billing import price_usd


client = TestClient(app)


def test_health() -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["service"] == "shipcheck"


def test_health_advertises_mcp() -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["mcp"] is True


def test_qa_preview_rejects_localhost() -> None:
    r = client.post(
        "/qa_preview",
        json={
            "url": "https://127.0.0.1/",
            "stories": [{"id": "home", "steps": [], "expect": "x"}],
        },
    )
    assert r.status_code == 400
    assert "unsafe" in r.json()["detail"].lower()


def test_qa_preview_rejects_file() -> None:
    r = client.post(
        "/qa_preview",
        json={
            "url": "file:///etc/passwd",
            "stories": [{"id": "home", "steps": [], "expect": "x"}],
        },
    )
    assert r.status_code == 400


def test_qa_preview_rejects_rfc1918() -> None:
    for url in (
        "https://10.0.0.8/app",
        "https://192.168.1.20/",
        "https://172.16.4.4/",
        "https://169.254.169.254/latest/meta-data/",
    ):
        r = client.post(
            "/qa_preview",
            json={"url": url, "stories": [{"id": "a", "steps": [], "expect": ""}]},
        )
        assert r.status_code == 400, url


def test_qa_preview_queues_public_url() -> None:
    r = client.post(
        "/qa_preview",
        json={
            "url": "https://example.com/",
            "stories": [{"id": "home", "steps": ["open"], "expect": "Example Domain"}],
            "viewport": "desktop",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "queued"
    assert body["job_id"].startswith("sc_")
    assert body["price_usd"] == 6
    job_id = body["job_id"]

    st = client.get(f"/qa_status/{job_id}")
    assert st.status_code == 200
    assert st.json()["status"] == "queued"

    rep = client.get(f"/qa_get_report/{job_id}")
    assert rep.status_code == 200
    assert rep.json()["job_id"] == job_id


def test_unknown_job() -> None:
    r = client.get("/qa_status/sc_doesnotexist")
    assert r.status_code == 404


def test_pricing() -> None:
    assert price_usd("desktop", 1) == 6
    assert price_usd("mobile", 4) == 6
    assert price_usd("both", 1) == 10
    assert price_usd("desktop", 5) == 10


def test_validation_story_count() -> None:
    r = client.post(
        "/qa_preview",
        json={"url": "https://example.com/", "stories": []},
    )
    assert r.status_code == 422


def test_qa_note_closes_needs_review() -> None:
    from shipcheck.store import create_job, save_job

    job = create_job(
        {
            "url": "https://example.com/",
            "stories": [{"id": "home", "steps": [], "expect": "Example Domain"}],
            "viewport": "desktop",
            "price_usd": 6,
        }
    )
    job["status"] = "needs_review"
    save_job(job)
    r = client.post(
        f"/qa_note/{job['job_id']}",
        json={"human_note": "Checkout works; false positive on NaN in footer.", "verdict": "pass"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "pass"
    assert body["human_note"].startswith("Checkout works")
    assert body["human_verdict"] == "pass"


def test_qa_note_rejects_queued() -> None:
    from shipcheck.store import create_job

    job = create_job(
        {
            "url": "https://example.com/",
            "stories": [{"id": "home", "steps": [], "expect": "x"}],
            "viewport": "desktop",
            "price_usd": 6,
        }
    )
    r = client.post(
        f"/qa_note/{job['job_id']}",
        json={"human_note": "too soon", "verdict": "fail"},
    )
    assert r.status_code == 409


def test_head_landing_and_health() -> None:
    r = client.head("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    h = client.head("/health")
    assert h.status_code == 200


def test_landing_page() -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    body = r.text
    assert "ShipCheck" in body
    assert "qa_preview" in body
    assert "qa_status" in body
    assert "qa_get_report" in body
    assert "$6" in body
    assert "$10" in body
    assert "mcpServers" in body
    assert "rejected" in body.lower() or "localhost" in body.lower()


def test_rate_limit_public_ip() -> None:
    old = os.environ.get("SHIPCHECK_PREVIEW_LIMIT_PER_IP")
    os.environ["SHIPCHECK_PREVIEW_LIMIT_PER_IP"] = "2"
    payload = {
        "url": "https://example.com/",
        "stories": [{"id": "home", "steps": ["open"], "expect": "Example Domain"}],
        "viewport": "desktop",
    }
    headers = {"CF-Connecting-IP": f"198.51.100.{(uuid.uuid4().int % 200) + 20}"}
    try:
        r1 = client.post("/qa_preview", json=payload, headers=headers)
        r2 = client.post("/qa_preview", json=payload, headers=headers)
        r3 = client.post("/qa_preview", json=payload, headers=headers)
        assert r1.status_code == 200, r1.text
        assert r2.status_code == 200, r2.text
        assert r3.status_code == 429, r3.text
        assert "rate limit" in r3.json()["detail"].lower()
    finally:
        if old is None:
            os.environ.pop("SHIPCHECK_PREVIEW_LIMIT_PER_IP", None)
        else:
            os.environ["SHIPCHECK_PREVIEW_LIMIT_PER_IP"] = old

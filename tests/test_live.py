"""Optional live run. Requires Playwright Chromium and egress to example.com."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("SHIPCHECK_HOME", "/workspace/shipcheck")

from shipcheck.runner import run_job
from shipcheck.store import create_job


def _chromium_ok() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            browser.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.live


@pytest.mark.skipif(not _chromium_ok(), reason="Playwright Chromium not installed")
def test_example_com_desktop_smoke_needs_review() -> None:
    job = create_job(
        {
            "url": "https://example.com/",
            "stories": [
                {
                    "id": "home",
                    "steps": ["open homepage"],
                    "expect": "Example Domain",
                }
            ],
            "viewport": "desktop",
            "price_usd": 6,
        }
    )
    done = run_job(job)
    # Homepage expect-only is smoke, not a pass.
    assert done["status"] == "needs_review", done
    assert "smoke only — no interaction" in (done.get("human_note") or "")
    stories = done["report"]["stories"]
    assert len(stories) == 1
    assert stories[0]["http_status"] == 200
    assert stories[0]["empty_body"] is False
    assert stories[0]["expect_missing"] == []
    assert stories[0]["status"] == "pass"  # heuristics green; job is still smoke
    assert stories[0]["screenshot"]
    assert done["report"]["summary"].get("smoke_only") is True
    shot = "/workspace/shipcheck/" + stories[0]["screenshot"]
    assert os.path.isfile(shot)
    assert os.path.getsize(shot) > 1000

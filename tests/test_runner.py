"""Unit tests for visible clicks, analytics 429, smoke-only reports."""

from __future__ import annotations

import pytest

from shipcheck.runner import (
    _run_structured_step,
    _story_result,
    build_findings,
    compose_human_note,
    finalize_job_report,
    is_smoke_only,
)


class _El:
    def __init__(self, name: str, visible: bool = True) -> None:
        self.name = name
        self.visible = visible
        self.clicks = 0

    def click(self, timeout: int = 5000) -> None:
        self.clicks += 1

    def is_visible(self) -> bool:
        return self.visible


class _Loc:
    def __init__(self, els: list[_El]) -> None:
        self._els = els
        self.filter_calls: list[dict] = []

    def filter(self, **kwargs):
        self.filter_calls.append(kwargs)
        if kwargs.get("visible") is True:
            return _Loc([e for e in self._els if e.visible])
        return self

    @property
    def first(self) -> _El:
        if not self._els:
            raise RuntimeError("no matches")
        return self._els[0]


class _Page:
    def __init__(self, loc: _Loc) -> None:
        self._loc = loc
        self.body = ""

    def get_by_text(self, text: str, exact: bool = False) -> _Loc:
        return self._loc

    def locator(self, sel: str) -> _Loc:
        return self._loc

    def inner_text(self, sel: str) -> str:
        return self.body


def _ok_story(**kwargs):
    base = dict(
        story_id="home",
        viewport="desktop",
        http_status=200,
        final_url="https://example.com/",
        console_errors=[],
        failed_network=[],
        empty_body=False,
        suspicious_text=[],
        expect_missing=[],
        step_errors=[],
        screenshot="reports/x/home-desktop.png",
        ssrf=[],
        actions=[],
    )
    base.update(kwargs)
    return _story_result(**base)


def test_click_prefers_visible_text() -> None:
    hidden = _El("mobile-nav", visible=False)
    hero = _El("hero-cta", visible=True)
    loc = _Loc([hidden, hero])  # hidden is first in the DOM
    page = _Page(loc)
    action, err = _run_structured_step(page, "click:text=Get started")
    assert err is None
    assert action == "clicked text=Get started"
    assert hero.clicks == 1
    assert hidden.clicks == 0
    assert loc.filter_calls and loc.filter_calls[0].get("visible") is True


def test_click_prefers_visible_css() -> None:
    hidden = _El("drawer-btn", visible=False)
    sticky = _El("sticky-btn", visible=True)
    loc = _Loc([hidden, sticky])
    page = _Page(loc)
    action, err = _run_structured_step(page, "click:.book-cta")
    assert err is None
    assert action == "clicked .book-cta"
    assert sticky.clicks == 1
    assert hidden.clicks == 0


def test_analytics_429_does_not_fail() -> None:
    result = _ok_story(
        console_errors=[
            "Failed to load resource: the server responded with a status of 429 () "
            "[https://www.google-analytics.com/g/collect?v=2]"
        ],
        failed_network=[
            "script https://www.google-analytics.com/g/collect net::ERR_ABORTED"
        ],
    )
    assert result["status"] == "pass"
    assert result["failures"] == []
    assert result["console_errors"]  # still recorded


def test_gtag_collect_console_does_not_fail() -> None:
    result = _ok_story(
        console_errors=[
            "Failed to load resource: the server responded with a status of 429 () "
            "[https://www.googletagmanager.com/gtag/js?id=G-XXXX]"
        ],
    )
    assert result["status"] == "pass"
    assert result["failures"] == []


def test_real_console_error_still_fails() -> None:
    result = _ok_story(
        console_errors=["Uncaught TypeError: Cannot read properties of null"],
    )
    assert result["status"] == "fail"
    assert any("console error" in f for f in result["failures"])


def test_smoke_only_stories_need_review() -> None:
    stories = [{"id": "home", "steps": ["open homepage"], "expect": "Example Domain"}]
    results = [
        _ok_story(actions=[]),
    ]
    assert is_smoke_only(stories, results) is True
    status, note, report = finalize_job_report(results=results, stories=stories)
    assert status == "needs_review"
    assert "smoke only — no interaction" in note
    assert report["summary"]["smoke_only"] is True
    assert "looks fine" not in note.lower()


def test_click_story_can_pass() -> None:
    stories = [
        {
            "id": "book",
            "steps": ["click:text=Book now", "see:Cart"],
            "expect": "Cart",
        }
    ]
    results = [_ok_story(story_id="book", actions=["clicked text=Book now", "saw Cart"])]
    assert is_smoke_only(stories, results) is False
    status, note, report = finalize_job_report(results=results, stories=stories)
    assert status == "pass"
    assert "clicked text=Book now" in note
    assert report["findings"] == []


def test_findings_from_step_errors_and_expect_missing() -> None:
    results = [
        _ok_story(
            story_id="checkout",
            expect_missing=["weekly rate"],
            step_errors=["step failed (click:text=Checkout): Timeout"],
        )
    ]
    findings = build_findings(results)
    assert len(findings) == 2
    assert all(f["severity"] == "high" for f in findings)
    titles = {f["title"] for f in findings}
    assert any("step failed" in t for t in titles)
    assert any("expect missing" in t for t in titles)
    status, note, report = finalize_job_report(
        results=results,
        stories=[{"id": "checkout", "steps": ["click:text=Checkout"], "expect": "weekly rate"}],
    )
    assert status == "needs_review"
    assert report["findings"] == findings
    assert "structured finding" in note


def test_human_note_not_looks_fine() -> None:
    note = compose_human_note(
        status="needs_review",
        results=[_ok_story(actions=[])],
        smoke=True,
        findings=[],
    )
    assert "Verdict: needs_review" in note
    assert "Clicked: (none)" in note
    assert "looks fine" not in note.lower()


def test_click_visible_not_hidden_dom_first_playwright() -> None:
    """Real browser: hidden mobile CTA is first in DOM; visible hero must win."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed")
    html = """<!doctype html>
<html><body>
<nav style="display:none"><button id="hidden-cta">Get started</button></nav>
<section><button id="hero-cta">Get started</button></section>
<script>
  document.getElementById('hidden-cta').onclick = () => { window.__clicked = 'hidden'; };
  document.getElementById('hero-cta').onclick = () => { window.__clicked = 'hero'; };
</script>
</body></html>"""
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            try:
                page = browser.new_page()
                page.set_content(html)
                action, err = _run_structured_step(page, "click:text=Get started")
                assert err is None, err
                assert action == "clicked text=Get started"
                assert page.evaluate("window.__clicked") == "hero"
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001
        if "chromium" in str(exc).lower() or "executable" in str(exc).lower():
            pytest.skip(f"chromium unavailable: {exc}")
        raise

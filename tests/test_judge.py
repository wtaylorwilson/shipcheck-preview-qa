"""Judge v0 rubric: observed-only findings, smoke still needs_review."""

from __future__ import annotations

from shipcheck.judge import apply_rubric, parse_daily_weekly
from shipcheck.runner import _story_result, finalize_job_report, is_smoke_only


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


GOAL = "Walk booking and check a Sat-Sat week uses the weekly rate"


def test_smoke_only_still_needs_review() -> None:
    stories = [{"id": "charter", "steps": ["explore"], "expect": ""}]
    results = [_ok_story(story_id="charter", actions=[])]
    assert is_smoke_only(stories, results) is True
    status, note, report = finalize_job_report(
        results=results, stories=stories, goal=GOAL
    )
    assert status == "needs_review"
    assert "smoke only — no interaction" in note
    titles = {f["title"] for f in report["findings"]}
    assert "smoke only" in titles
    assert report["summary"]["smoke_only"] is True


def test_dead_cta_same_url() -> None:
    result = _ok_story(story_id="charter", actions=["clicked Book now"])
    result["explore"] = {
        "clicked": {"text": "Book now", "href": "#"},
        "same_url": True,
        "page_changed": False,
        "prices": [],
        "date_inputs": [],
    }
    extras = apply_rubric(results=[result], stories=[], goal=GOAL, smoke=False)
    assert any(f["title"] == "dead CTA" and f["severity"] == "high" for f in extras)


def test_money_day_week_mismatch() -> None:
    daily, weekly = parse_daily_weekly(["$100 / day", "$800 / week"])
    assert daily == [100.0]
    assert weekly == [800.0]
    result = _ok_story(story_id="charter", actions=["clicked Book now"])
    result["explore"] = {
        "clicked": {"text": "Book now"},
        "same_url": False,
        "page_changed": True,
        "prices": ["$100 / day", "$800 / week"],
        "date_inputs": [],
    }
    extras = apply_rubric(results=[result], stories=[], goal=GOAL, smoke=False)
    assert any("day/week" in f["title"] for f in extras)


def test_does_not_invent_money_without_rates() -> None:
    result = _ok_story(story_id="charter", actions=["clicked Book now"])
    result["explore"] = {
        "clicked": {"text": "Book now"},
        "same_url": False,
        "page_changed": True,
        "prices": ["$250"],
        "date_inputs": [],
    }
    extras = apply_rubric(results=[result], stories=[], goal=None, smoke=False)
    assert not any(f["title"].startswith("money") for f in extras)


def test_copy_vs_behavior_dates() -> None:
    result = _ok_story(story_id="charter", actions=["clicked Book now"])
    result["explore"] = {
        "clicked": {"text": "Book now"},
        "same_url": False,
        "page_changed": True,
        "prices": ["$100 / day"],
        "date_inputs": [],
    }
    extras = apply_rubric(results=[result], stories=[], goal=GOAL, smoke=False)
    assert any(f["title"] == "copy vs behavior" for f in extras)


def test_off_by_one_dates() -> None:
    result = _ok_story(story_id="charter", actions=["clicked Book now"])
    result["explore"] = {
        "clicked": {"text": "Book now"},
        "same_url": False,
        "page_changed": True,
        "prices": [],
        "date_inputs": [
            {"name": "checkin", "value": "2026-08-22", "visible": True},
            {"name": "checkout", "value": "2026-08-29", "visible": True},
        ],
        "nights_mentions": [8],
    }
    extras = apply_rubric(results=[result], stories=[], goal=GOAL, smoke=False)
    assert any("off-by-one" in f["title"] for f in extras)

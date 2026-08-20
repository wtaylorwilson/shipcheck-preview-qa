"""Playwright heuristic runner. Independent of the HTTP server."""

from __future__ import annotations

import re
import time
from typing import Any

from shipcheck.billing import debit
from shipcheck.explorer import (
    collect_page_observations,
    explore_goal_from_step,
    is_explore_step,
    run_explorer,
)
from shipcheck.judge import apply_rubric
from shipcheck.models import expect_list
from shipcheck.paths import ensure_dirs
from shipcheck.ssrf import JOB_CAP_S, NAV_TIMEOUT_S, UnsafeUrl, assert_url_allowed
from shipcheck.store import save_job, screenshot_dir, utcnow

NAV_TIMEOUT_MS = NAV_TIMEOUT_S * 1000
SUSPICIOUS = re.compile(
    r"\b(undefined|NaN|TypeError|ReferenceError|SyntaxError|Internal Server Error|"
    r"Unhandled(?: Promise)? Rejection)\b"
    r"|Something went wrong"
    r"|Application error"
    r"|This page isn't working",
    re.IGNORECASE,
)

# Third-party analytics / tag-manager noise. Recorded, but not a story failure.
ANALYTICS_NOISE = re.compile(
    r"google-analytics\.com|"
    r"googletagmanager\.com|"
    r"analytics\.google\.com|"
    r"/g/collect\b|"
    r"/gtag/js|"
    r"googleadservices\.com|"
    r"doubleclick\.net",
    re.IGNORECASE,
)
CONSOLE_429 = re.compile(
    r"status of 429|\bHTTP 429\b|net::ERR_[A-Z0-9_]*429",
    re.IGNORECASE,
)

VIEWPORTS = {
    "desktop": {"width": 1280, "height": 800, "is_mobile": False},
    "mobile": {"width": 390, "height": 844, "is_mobile": True},
}


def _viewports_for(kind: str) -> list[str]:
    if kind == "both":
        return ["desktop", "mobile"]
    return [kind]


def _collect_suspicious(text: str) -> list[str]:
    hits = sorted({m.group(0) for m in SUSPICIOUS.finditer(text or "")})
    return hits


def is_analytics_noise(text: str) -> bool:
    return bool(ANALYTICS_NOISE.search(text or ""))


def actionable_console_errors(
    console_errors: list[str],
    failed_network: list[str] | None = None,
) -> list[str]:
    """Console errors that should fail a story. Analytics / 429 noise is dropped."""
    failed_network = failed_network or []
    analytics_net = any(is_analytics_noise(x) for x in failed_network)
    out: list[str] = []
    for err in console_errors:
        if is_analytics_noise(err):
            continue
        if CONSOLE_429.search(err or ""):
            continue
        if analytics_net and re.search(r"Failed to load resource|net::ERR_", err or "", re.I):
            continue
        out.append(err)
    return out


def _base_locator(page, sel: str):
    if sel.startswith("text="):
        return page.get_by_text(sel[5:].strip(), exact=False)
    return page.locator(sel)


def prefer_visible(loc):
    """Return a locator restricted to visible matches when Playwright supports it."""
    filt = getattr(loc, "filter", None)
    if callable(filt):
        try:
            return loc.filter(visible=True)
        except TypeError:
            return loc
    return loc


def click_visible(page, sel: str, timeout: int = 5000) -> None:
    """Click the first *visible* match. Hidden mobile-nav CTAs must not win."""
    prefer_visible(_base_locator(page, sel)).first.click(timeout=timeout)


def _run_structured_step(page, step: str) -> tuple[str | None, str | None]:
    """Execute click:/fill:/wait:/see: steps.

    Returns (action, error). Notes and empty steps return (None, None).
    """
    raw = (step or "").strip()
    if not raw:
        return None, None
    lower = raw.lower()
    try:
        if lower.startswith("click:"):
            sel = raw.split(":", 1)[1].strip()
            click_visible(page, sel, timeout=5000)
            return f"clicked {sel}", None
        if lower.startswith("fill:"):
            rest = raw.split(":", 1)[1]
            if "|" not in rest:
                return None, "fill: needs selector|value"
            sel, value = rest.split("|", 1)
            page.locator(sel.strip()).first.fill(value, timeout=5000)
            return f"filled {sel.strip()}", None
        if lower.startswith("wait:"):
            rest = raw.split(":", 1)[1].strip()
            if rest.isdigit():
                page.wait_for_timeout(min(int(rest), 10000))
            else:
                page.locator(rest).first.wait_for(timeout=8000)
            return f"waited {rest}", None
        if lower.startswith("see:"):
            needle = raw.split(":", 1)[1].strip()
            body = page.inner_text("body") or ""
            if needle.lower() not in body.lower():
                return None, f"see: not found: {needle!r}"
            return f"saw {needle}", None
    except Exception as exc:  # noqa: BLE001 — step failures become heuristic notes
        return None, f"step failed ({raw[:80]}): {exc}"
    return None, None


def _story_result(
    *,
    story_id: str,
    viewport: str,
    http_status: int | None,
    final_url: str | None,
    console_errors: list[str],
    failed_network: list[str],
    empty_body: bool,
    suspicious_text: list[str],
    expect_missing: list[str],
    step_errors: list[str],
    screenshot: str | None,
    ssrf: list[str],
    actions: list[str] | None = None,
) -> dict[str, Any]:
    failures: list[str] = []
    if ssrf:
        failures.extend(f"ssrf: {x}" for x in ssrf)
    if http_status is None:
        failures.append("no HTTP status for main document")
    elif http_status >= 400 or http_status < 200:
        failures.append(f"HTTP {http_status}")
    if empty_body:
        failures.append("empty body")
    actionable = actionable_console_errors(console_errors, failed_network)
    if actionable:
        failures.append(f"{len(actionable)} console error(s)")
    # Main-document network failures already covered by HTTP status.
    # Subresource requestfailed is recorded; fail the story if any document failed.
    doc_fails = [f for f in failed_network if f.startswith("document ")]
    if doc_fails:
        failures.append("main document request failed")
    if suspicious_text:
        failures.append("suspicious visible text: " + ", ".join(suspicious_text[:8]))
    if expect_missing:
        failures.append("expect not found: " + "; ".join(expect_missing[:4]))
    if step_errors:
        failures.extend(step_errors)
    status = "fail" if failures else "pass"
    return {
        "id": story_id,
        "viewport": viewport,
        "status": status,
        "http_status": http_status,
        "final_url": final_url,
        "console_errors": console_errors[:20],
        "failed_network": failed_network[:30],
        "empty_body": empty_body,
        "suspicious_text": suspicious_text,
        "expect_missing": expect_missing,
        "step_errors": step_errors,
        "actions": list(actions or []),
        "screenshot": screenshot,
        "failures": failures,
    }


def build_findings(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Structured findings for step_errors / expect_missing (agent-consumable)."""
    findings: list[dict[str, Any]] = []
    for r in results:
        sid = r.get("id") or "story"
        vp = r.get("viewport") or ""
        prefix = f"{sid}" + (f" ({vp})" if vp else "")
        for err in r.get("step_errors") or []:
            findings.append(
                {
                    "severity": "high",
                    "title": f"{prefix}: step failed",
                    "detail": str(err),
                }
            )
        for miss in r.get("expect_missing") or []:
            findings.append(
                {
                    "severity": "high",
                    "title": f"{prefix}: expect missing",
                    "detail": f"{miss!r} was not visible after the story",
                }
            )
    return findings


def is_smoke_only(stories: list[dict[str, Any]], results: list[dict[str, Any]]) -> bool:
    """True when heuristics are green but we never clicked or filled."""
    if any(r.get("status") == "fail" for r in results):
        return False
    for r in results:
        for action in r.get("actions") or []:
            al = str(action).lower()
            if al.startswith("clicked ") or al.startswith("filled "):
                return False
    return True


def compose_human_note(
    *,
    status: str,
    results: list[dict[str, Any]],
    smoke: bool,
    findings: list[dict[str, Any]],
    goal: str | None = None,
) -> str:
    """Short findings brief — not 'looks fine'."""
    acted: list[str] = []
    for r in results:
        sid = r.get("id") or "story"
        for action in r.get("actions") or []:
            acted.append(f"{sid}: {action}")
    failed: list[str] = []
    for r in results:
        if r.get("status") != "fail":
            continue
        bits = r.get("failures") or []
        failed.append(
            f"{r.get('id')}[{r.get('viewport')}]: " + "; ".join(str(b) for b in bits[:4])
        )
    parts = [f"Verdict: {status}."]
    if goal:
        parts.append(f"Charter: {goal[:240]}.")
    parts.append("Clicked: " + ("; ".join(acted[:16]) if acted else "(none)") + ".")
    parts.append("Failed: " + (" | ".join(failed[:8]) if failed else "(none)") + ".")
    if smoke:
        parts.append("smoke only — no interaction")
    else:
        idle = [r.get("id") for r in results if not r.get("actions")]
        if idle:
            parts.append(
                "Smoke checks (no click:/fill:): "
                + ", ".join(str(s) for s in idle[:8])
                + "."
            )
    if findings:
        parts.append(f"{len(findings)} structured finding(s).")
    return " ".join(parts)[:4000]


def finalize_job_report(
    *,
    results: list[dict[str, Any]],
    stories: list[dict[str, Any]],
    goal: str | None = None,
) -> tuple[str, str, dict[str, Any]]:
    """Decide job status, write the findings brief, attach report JSON."""
    any_fail = any(r.get("status") == "fail" for r in results)
    findings = build_findings(results)
    smoke = is_smoke_only(stories, results)
    findings.extend(apply_rubric(results=results, stories=stories, goal=goal, smoke=smoke))
    high = any(str(f.get("severity") or "").lower() == "high" for f in findings)
    status = "needs_review" if (any_fail or smoke or high) else "pass"
    note = compose_human_note(
        status=status, results=results, smoke=smoke, findings=findings, goal=goal
    )
    report = {
        "stories": results,
        "summary": {
            "n_stories": len(results),
            "n_failed": sum(1 for r in results if r.get("status") == "fail"),
            "n_passed": sum(1 for r in results if r.get("status") == "pass"),
            "smoke_only": smoke,
        },
        "findings": findings,
    }
    if goal:
        report["goal"] = goal
        report["summary"]["goal"] = goal
    return status, note, report


def run_job(job: dict[str, Any]) -> dict[str, Any]:
    """Run heuristics for every story × viewport. Mutates and persists `job`."""
    ensure_dirs()
    job_id = job["job_id"]
    url = job["url"]
    deadline = time.monotonic() + JOB_CAP_S
    job["status"] = "running"
    job["started_at"] = job.get("started_at") or utcnow()
    job["error"] = None
    save_job(job)

    try:
        assert_url_allowed(url, resolve=True)
    except UnsafeUrl as exc:
        job["status"] = "error"
        job["error"] = f"unsafe url: {exc}"
        job["finished_at"] = utcnow()
        save_job(job)
        return job

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        job["status"] = "error"
        job["error"] = f"playwright not installed: {exc}"
        job["finished_at"] = utcnow()
        save_job(job)
        return job

    stories = job.get("stories") or []
    viewports = _viewports_for(job.get("viewport") or "desktop")
    results: list[dict[str, Any]] = []
    shot_root = screenshot_dir(job_id)
    shot_root.mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(
                    headless=True,
                    args=["--disable-dev-shm-usage", "--no-sandbox"],
                )
            except Exception as exc:  # noqa: BLE001
                job["status"] = "error"
                job["error"] = f"chromium launch failed: {exc}"
                job["finished_at"] = utcnow()
                save_job(job)
                return job

            try:
                for vp_name in viewports:
                    if time.monotonic() > deadline:
                        raise TimeoutError("job exceeded 4 minute cap")
                    vp = VIEWPORTS[vp_name]
                    context = browser.new_context(
                        viewport={"width": vp["width"], "height": vp["height"]},
                        is_mobile=vp["is_mobile"],
                        ignore_https_errors=False,
                        java_script_enabled=True,
                    )
                    try:
                        for story in stories:
                            if time.monotonic() > deadline:
                                raise TimeoutError("job exceeded 4 minute cap")
                            results.append(
                                _run_one_story(
                                    context,
                                    job_id=job_id,
                                    url=url,
                                    story=story,
                                    vp_name=vp_name,
                                    shot_root=shot_root,
                                    deadline=deadline,
                                    goal=job.get("goal"),
                                )
                            )
                    finally:
                        context.close()
            finally:
                browser.close()
    except TimeoutError as exc:
        job["status"] = "error"
        job["error"] = str(exc)
        job["report"] = {"stories": results, "truncated": True}
        job["finished_at"] = utcnow()
        save_job(job)
        return job
    except Exception as exc:  # noqa: BLE001
        job["status"] = "error"
        job["error"] = f"runner crashed: {exc}"
        job["report"] = {"stories": results, "truncated": True}
        job["finished_at"] = utcnow()
        save_job(job)
        return job

    # Infrastructure ok → debit hook (no-op in v0). Heuristic fails are billed.
    debit_result = debit(
        api_key=job.get("api_key"),
        job_id=job_id,
        viewport=job.get("viewport") or "desktop",
        n_stories=len(stories),
    )
    job["billed"] = debit_result.billed
    job["billing_reason"] = debit_result.reason
    job["price_usd"] = debit_result.price_usd
    status, note, report = finalize_job_report(
        results=results, stories=stories, goal=job.get("goal")
    )
    job["status"] = status
    job["human_note"] = note
    job["report"] = report
    job["finished_at"] = utcnow()
    job["error"] = None
    save_job(job)
    return job


def _run_one_story(
    context,
    *,
    job_id: str,
    url: str,
    story: dict[str, Any],
    vp_name: str,
    shot_root,
    deadline: float,
    goal: str | None = None,
) -> dict[str, Any]:
    story_id = story["id"]
    page = context.new_page()
    page.set_default_navigation_timeout(NAV_TIMEOUT_MS)
    page.set_default_timeout(NAV_TIMEOUT_MS)

    console_errors: list[str] = []
    failed_network: list[str] = []
    ssrf_hits: list[str] = []
    http_status: int | None = None
    final_url: str | None = None

    def on_console(msg) -> None:
        if msg.type != "error":
            return
        loc_url = ""
        try:
            loc = msg.location
            if isinstance(loc, dict):
                loc_url = str(loc.get("url") or "")
            elif loc is not None:
                loc_url = str(getattr(loc, "url", "") or "")
        except Exception:
            loc_url = ""
        text = (msg.text or "")[:500]
        if loc_url:
            console_errors.append(f"{text} [{loc_url[:180]}]")
        else:
            console_errors.append(text)

    def on_pageerror(err) -> None:
        console_errors.append(str(err)[:500])

    def on_requestfailed(req) -> None:
        rtype = req.resource_type
        failed_network.append(f"{rtype} {req.url[:180]} {req.failure or 'failed'}")

    def on_response(resp) -> None:
        nonlocal http_status, final_url
        req = resp.request
        try:
            assert_url_allowed(resp.url, resolve=True)
        except UnsafeUrl as exc:
            ssrf_hits.append(str(exc))
            return
        if req.resource_type == "document" and http_status is None:
            http_status = resp.status
            final_url = resp.url
        elif req.resource_type == "document" and resp.status >= 400:
            failed_network.append(f"document {resp.url[:180]} HTTP {resp.status}")

    def route_guard(route) -> None:
        target = route.request.url
        try:
            assert_url_allowed(target, resolve=True)
        except UnsafeUrl as exc:
            ssrf_hits.append(str(exc))
            route.abort()
            return
        route.continue_()

    page.on("console", on_console)
    page.on("pageerror", on_pageerror)
    page.on("requestfailed", on_requestfailed)
    page.on("response", on_response)
    page.route("**/*", route_guard)

    step_errors: list[str] = []
    actions: list[str] = []
    explore_obs: list[dict[str, Any]] = []
    body_text = ""
    empty_body = True
    screenshot_rel = None

    remaining_ms = max(1000, int((deadline - time.monotonic()) * 1000))
    nav_timeout = min(NAV_TIMEOUT_MS, remaining_ms)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=nav_timeout)
        for step in story.get("steps") or []:
            if is_explore_step(step):
                step_goal = explore_goal_from_step(step, goal)
                obs, action, err = run_explorer(
                    page,
                    goal=step_goal,
                    job_id=job_id,
                    story_id=story_id,
                    vp_name=vp_name,
                    shot_root=shot_root,
                )
                if obs:
                    explore_obs.append(obs)
                if action:
                    actions.append(action)
                if err:
                    step_errors.append(err)
                continue
            action, err = _run_structured_step(page, step)
            if action:
                actions.append(action)
            if err:
                step_errors.append(err)
        if goal and not explore_obs:
            explore_obs.append(collect_page_observations(page, goal))
        try:
            body_text = page.inner_text("body") or ""
        except Exception:
            body_text = ""
        empty_body = len(body_text.strip()) < 20
        shot_name = f"{story_id}-{vp_name}.png"
        shot_path = shot_root / shot_name
        page.screenshot(path=str(shot_path), full_page=False)
        screenshot_rel = f"reports/{job_id}/{shot_name}"
    except Exception as exc:  # noqa: BLE001
        step_errors.append(f"navigation/run: {exc}")
        try:
            shot_name = f"{story_id}-{vp_name}.png"
            shot_path = shot_root / shot_name
            page.screenshot(path=str(shot_path), full_page=False)
            screenshot_rel = f"reports/{job_id}/{shot_name}"
        except Exception:
            screenshot_rel = None
    finally:
        page.close()

    if ssrf_hits:
        # Redirect-to-private must not produce a pass.
        empty_body = True if http_status is None else empty_body

    expect_missing = []
    for needle in expect_list(story.get("expect") or ""):
        if needle.lower() not in body_text.lower():
            expect_missing.append(needle)

    result = _story_result(
        story_id=story_id,
        viewport=vp_name,
        http_status=http_status,
        final_url=final_url,
        console_errors=console_errors,
        failed_network=failed_network,
        empty_body=empty_body,
        suspicious_text=_collect_suspicious(body_text),
        expect_missing=expect_missing,
        step_errors=step_errors,
        screenshot=screenshot_rel,
        ssrf=ssrf_hits,
        actions=actions,
    )
    if explore_obs:
        result["explore"] = explore_obs[0] if len(explore_obs) == 1 else explore_obs
    return result

"""Judge v0: fixed rubric over observed explorer/story evidence.

Categories: money, dead CTA, copy vs behavior, smoke-only.
Severity: high / med / low / info.
Do not invent bugs that were not observed.
"""

from __future__ import annotations

import re
from datetime import datetime, date
from typing import Any
from urllib.parse import urlsplit


DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d", "%d/%m/%Y")

GOAL_DATE_RE = re.compile(
    r"\b(date|dates|sat|saturday|sun|sunday|week|weekly|night|nights|"
    r"check[- ]?in|check[- ]?out)\b",
    re.IGNORECASE,
)
GOAL_PAY_RE = re.compile(
    r"\b(pay|payment|checkout|price|rate|rates|cart|total|weekly rate)\b",
    re.IGNORECASE,
)
GOAL_CART_RE = re.compile(r"\bcart\b", re.IGNORECASE)

RATE_RE = re.compile(
    r"\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*/\s*(day|night|daily|week|wk|weekly)",
    re.IGNORECASE,
)
FREE_DELIVERY_RE = re.compile(r"\bfree\s+delivery\b", re.IGNORECASE)
DELIVERY_FEE_RE = re.compile(
    r"\bdelivery\s+(?:fee|charge|cost)\b|\b\$\s*\d[\d,]*(?:\.\d{2})?\s+delivery\b",
    re.IGNORECASE,
)


def _explore_list(result: dict[str, Any]) -> list[dict[str, Any]]:
    raw = result.get("explore")
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    return []


def all_observations(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in results:
        out.extend(_explore_list(r))
    return out


def parse_daily_weekly(prices: list[str]) -> tuple[list[float], list[float]]:
    daily: list[float] = []
    weekly: list[float] = []
    for p in prices:
        m = RATE_RE.search(p or "")
        if not m:
            continue
        try:
            amt = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        unit = m.group(2).lower()
        if unit in ("day", "night", "daily"):
            daily.append(amt)
        else:
            weekly.append(amt)
    return daily, weekly


def parse_date_value(raw: str) -> date | None:
    s = (raw or "").strip()
    if not s:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s[:10] if fmt.startswith("%Y-%m-%d") else s, fmt).date()
        except ValueError:
            continue
    # datetime-local: 2026-08-22T15:00
    if "T" in s:
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def goal_topics(goal: str | None) -> set[str]:
    gl = goal or ""
    topics: set[str] = set()
    if GOAL_DATE_RE.search(gl):
        topics.add("dates")
    if GOAL_PAY_RE.search(gl):
        topics.add("pay")
    if GOAL_CART_RE.search(gl):
        topics.add("cart")
    return topics


def _finding(severity: str, title: str, detail: str) -> dict[str, str]:
    return {"severity": severity, "title": title, "detail": detail}


def _dedupe(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for f in findings:
        key = (str(f.get("title") or ""), str(f.get("detail") or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def _clicked_nothing(results: list[dict[str, Any]]) -> bool:
    for r in results:
        for action in r.get("actions") or []:
            al = str(action).lower()
            if al.startswith("clicked ") or al.startswith("filled "):
                return False
    return True


def _money_findings(obs_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    prices: list[str] = []
    date_values: list[str] = []
    nights: list[int] = []
    bodies_free_delivery = False
    bodies_delivery_fee = False
    for obs in obs_list:
        for p in obs.get("prices") or []:
            if p not in prices:
                prices.append(p)
        for d in obs.get("date_inputs") or []:
            val = str(d.get("value") or "").strip()
            if val and val not in date_values:
                date_values.append(val)
        for n in obs.get("nights_mentions") or []:
            if n not in nights:
                nights.append(n)
        blob = " ".join(str(x) for x in (obs.get("prices") or []) + (obs.get("validation") or []))
        # Also scan CTA texts for "free delivery"
        blob += " " + " ".join(str(c.get("text") or "") for c in (obs.get("ctas") or []))
        if FREE_DELIVERY_RE.search(blob):
            bodies_free_delivery = True
        if DELIVERY_FEE_RE.search(blob):
            bodies_delivery_fee = True

    daily, weekly = parse_daily_weekly(prices)
    flagged_ratio = False
    for d in daily:
        if d <= 0:
            continue
        for w in weekly:
            ratio = w / d
            # A week of stay is 5–7 billed days. 8+ is a classic off-by-one.
            if ratio >= 7.5:
                findings.append(
                    _finding(
                        "high" if ratio >= 7.8 else "med",
                        "money: day/week mismatch",
                        f"observed {d:g}/day and {w:g}/week (ratio {ratio:.2f})",
                    )
                )
                flagged_ratio = True
                break
            if 0 < ratio < 4.5:
                findings.append(
                    _finding(
                        "med",
                        "money: day/week mismatch",
                        f"observed {d:g}/day and {w:g}/week (ratio {ratio:.2f})",
                    )
                )
                flagged_ratio = True
                break
        if flagged_ratio:
            break

    parsed_dates = [parse_date_value(v) for v in date_values]
    parsed_dates = [d for d in parsed_dates if d is not None]
    if len(parsed_dates) >= 2 and nights:
        computed = abs((parsed_dates[1] - parsed_dates[0]).days)
        for shown in nights:
            if shown != computed and abs(shown - computed) == 1:
                findings.append(
                    _finding(
                        "high",
                        "money: off-by-one dates",
                        f"dates span {computed} nights but page shows {shown}",
                    )
                )
                break

    if bodies_free_delivery and bodies_delivery_fee:
        findings.append(
            _finding(
                "med",
                "money: delivery fee",
                "page advertises free delivery and also a delivery fee",
            )
        )

    return findings


def _dead_cta_findings(obs_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for obs in obs_list:
        clicked = obs.get("clicked") or {}
        label = ""
        if isinstance(clicked, dict):
            label = str(clicked.get("text") or "")
        if clicked and obs.get("same_url") and not obs.get("page_changed"):
            findings.append(
                _finding(
                    "high",
                    "dead CTA",
                    f"click on {label!r} did nothing (same URL, no visible change)",
                )
            )
        hidden = obs.get("hidden_only_target")
        if hidden:
            findings.append(
                _finding(
                    "med",
                    "dead CTA",
                    f"target {hidden!r} was hidden-only",
                )
            )
    return findings


def _copy_vs_behavior(goal: str | None, obs_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not goal or not obs_list:
        return []
    topics = goal_topics(goal)
    if not topics:
        return []
    findings: list[dict[str, Any]] = []
    date_inputs: list[dict[str, Any]] = []
    prices: list[str] = []
    clicked_any = False
    urls: list[str] = []
    for obs in obs_list:
        date_inputs.extend(obs.get("date_inputs") or [])
        for p in obs.get("prices") or []:
            if p not in prices:
                prices.append(p)
        if obs.get("clicked"):
            clicked_any = True
        for key in ("url_after", "url", "url_before"):
            u = obs.get(key)
            if u:
                urls.append(str(u).lower())

    if "dates" in topics:
        visible_dates = [d for d in date_inputs if d.get("visible", True)]
        if not visible_dates:
            findings.append(
                _finding(
                    "med",
                    "copy vs behavior",
                    "goal mentions dates but no date inputs were visible",
                )
            )

    if ("pay" in topics or "cart" in topics) and clicked_any:
        path_blob = " ".join(urlsplit(u).path for u in urls)
        cartish = any(w in path_blob for w in ("cart", "checkout", "book", "order"))
        if not prices and not cartish:
            findings.append(
                _finding(
                    "med",
                    "copy vs behavior",
                    "goal mentions pay/cart but after the click no price or cart/checkout UI was observed",
                )
            )
    return findings


def apply_rubric(
    *,
    results: list[dict[str, Any]],
    stories: list[dict[str, Any]],
    goal: str | None = None,
    smoke: bool | None = None,
) -> list[dict[str, Any]]:
    """Extra findings from the charter rubric. Caller already has step/expect findings."""
    _ = stories
    extras: list[dict[str, Any]] = []
    obs_list = all_observations(results)
    nothing = _clicked_nothing(results)
    if smoke is True or (smoke is None and nothing and not any(r.get("status") == "fail" for r in results)):
        extras.append(
            _finding(
                "med",
                "smoke only",
                "nothing was clicked — needs_review",
            )
        )
    extras.extend(_dead_cta_findings(obs_list))
    extras.extend(_money_findings(obs_list))
    extras.extend(_copy_vs_behavior(goal, obs_list))
    return _dedupe(extras)

"""Deterministic charter explorer (v0). No LLM, no extra keys.

Given a public URL + goal text, collect visible primary CTAs, click the
most relevant one (visible-first), then a cart/setup/review control when
the goal mentions dates/week/cart. Fill a Sat-Sat ISO pair when the goal
asks for a week. Record duration text and totals. Never fill payment
fields. Never submit Send / Submit request / Pay / Place order.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from shipcheck.models import Story

PRIMARY_WORDS = ("book", "buy", "checkout", "cart", "setup", "rent", "continue", "add")

# Goal stems → which primary word the charter is asking for.
GOAL_STEMS: dict[str, tuple[str, ...]] = {
    "book": ("book", "booking", "booked"),
    "buy": ("buy", "buying"),
    "checkout": ("checkout", "check-out"),
    "cart": ("cart", "basket"),
    "setup": ("setup", "set-up"),
    "rent": ("rent", "rental", "renting"),
    "continue": ("continue",),
    "add": ("add", "add-to-cart"),
}

FORBIDDEN_SUBMIT_RE = re.compile(
    r"\bplace\s+order\b"
    r"|\bsubmit(?:\s+request)?\b"
    r"|^\s*send\b"
    r"|\b(?:pay|payment)\b",
    re.IGNORECASE,
)

PAYMENT_FIELD_RE = re.compile(
    r"card(?:number|holder)?|cc[-_]?(?:num|exp)|cvc|cvv|expir|iban|routing|account.?number",
    re.IGNORECASE,
)

PRICE_RE = re.compile(
    r"\$\s*\d{1,3}(?:,\d{3})*(?:\.\d{2})?"
    r"(?:\s*/\s*(?:day|night|week|wk|daily|weekly))?"
    r"|\b\d{1,3}(?:,\d{3})*(?:\.\d{2})?\s*/\s*(?:day|night|week|wk)\b",
    re.IGNORECASE,
)

NIGHTS_RE = re.compile(r"\b(\d+)\s*(nights?|days?)\b", re.IGNORECASE)

FOLLOWUP_WORDS = ("cart", "setup", "review")

GOAL_FOLLOWUP_RE = re.compile(
    r"\b(dates?|week(?:ly)?|sat[- ]?sat|cart|nightly|nights?)\b",
    re.IGNORECASE,
)
GOAL_WEEK_RE = re.compile(
    r"\b(week(?:ly)?|sat[- ]?sat|sat(?:urday)?\s*[-–to]+\s*sat(?:urday)?)\b",
    re.IGNORECASE,
)
CART_TOTAL_RE = re.compile(
    r"(?:cart\s+)?(?:sub)?total(?:\s+due)?\s*:?\s*\$\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)"
    r"|\$\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*(?:total)\b",
    re.IGNORECASE,
)
START_DATE_NAME_RE = re.compile(
    r"deliver|check[-_ ]?in|start|from|begin|arriv", re.IGNORECASE
)
END_DATE_NAME_RE = re.compile(
    r"pick[-_ ]?up|check[-_ ]?out|end\b|until|depart|return", re.IGNORECASE
)

CTA_JS = """() => {
  const nodes = Array.from(document.querySelectorAll(
    'a, button, [role="button"], input[type="submit"], input[type="button"]'
  ));
  function isVisible(el) {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    const st = window.getComputedStyle(el);
    if (!st || st.display === "none" || st.visibility === "hidden" || Number(st.opacity) === 0) {
      return false;
    }
    return true;
  }
  return nodes.map((el) => {
    const text = ((el.innerText || el.value || el.getAttribute("aria-label") || "") + "")
      .replace(/\\s+/g, " ")
      .trim()
      .slice(0, 80);
    return {
      text,
      tag: (el.tagName || "").toLowerCase(),
      href: el.href || el.getAttribute("href") || "",
      visible: isVisible(el),
      type: el.getAttribute("type") || "",
    };
  }).filter((x) => x.text);
}"""

DATE_JS = """() => {
  const els = Array.from(document.querySelectorAll(
    'input[type="date"], input[type="datetime-local"], input[name*="date" i], input[id*="date" i], input[placeholder*="date" i], input[aria-label*="date" i]'
  ));
  return els.map((el) => ({
    name: el.name || el.id || "",
    type: el.type || "",
    value: (el.value || "").trim(),
    visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
  }));
}"""

VALIDATION_JS = """() => {
  const els = Array.from(document.querySelectorAll(
    '[role="alert"], [aria-invalid="true"], .error, .invalid-feedback, .field-error'
  ));
  return els
    .map((el) => ((el.innerText || el.textContent || "") + "").replace(/\\s+/g, " ").trim().slice(0, 160))
    .filter(Boolean);
}"""


def is_forbidden_submit(text: str) -> bool:
    """True for Send / Submit request / Pay / Place order (and close cousins)."""
    tl = " ".join((text or "").split())
    if not tl:
        return False
    return bool(FORBIDDEN_SUBMIT_RE.search(tl))


def is_payment_field(selector: str) -> bool:
    return bool(PAYMENT_FIELD_RE.search(selector or ""))


def is_primary_cta(text: str) -> bool:
    tl = (text or "").lower()
    return any(re.search(rf"\b{re.escape(w)}\b", tl) for w in PRIMARY_WORDS)


def goal_mentions(goal: str, word: str) -> bool:
    stems = GOAL_STEMS.get(word, (word,))
    gl = goal or ""
    return any(re.search(rf"\b{re.escape(s)}\b", gl, re.IGNORECASE) for s in stems)


def score_cta(text: str, goal: str) -> int:
    """Higher = more relevant to the charter. Deterministic, boring."""
    score = 0
    for word in PRIMARY_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", text or "", re.IGNORECASE):
            score += 10
            if goal_mentions(goal, word):
                score += 20
    raw = " ".join((text or "").lower().split())
    if raw and raw in (goal or "").lower():
        score += 15
    return score


def choose_cta(ctas: list[dict[str, Any]], goal: str) -> dict[str, Any] | None:
    """Most relevant *visible* primary CTA that is not a submit/pay button."""
    allowed = [
        c
        for c in ctas
        if c.get("visible")
        and is_primary_cta(str(c.get("text") or ""))
        and not is_forbidden_submit(str(c.get("text") or ""))
    ]
    if not allowed:
        return None
    allowed.sort(key=lambda c: (-score_cta(str(c.get("text") or ""), goal), str(c.get("text") or "").lower()))
    return allowed[0]


def find_hidden_only_target(ctas: list[dict[str, Any]], goal: str | None) -> str | None:
    if not goal:
        return None
    hidden = [
        c
        for c in ctas
        if not c.get("visible") and is_primary_cta(str(c.get("text") or ""))
    ]
    visible = [
        c
        for c in ctas
        if c.get("visible") and is_primary_cta(str(c.get("text") or ""))
    ]
    best_hidden = None
    best_score = 0
    for c in hidden:
        s = score_cta(str(c.get("text") or ""), goal)
        if s > best_score:
            best_score = s
            best_hidden = str(c.get("text") or "")
    if best_hidden and best_score >= 20:
        vis_best = max((score_cta(str(c.get("text") or ""), goal) for c in visible), default=0)
        if vis_best < best_score:
            return best_hidden
    return None


def extract_prices(text: str) -> list[str]:
    seen: list[str] = []
    for m in PRICE_RE.finditer(text or ""):
        token = " ".join(m.group(0).split())
        if token not in seen:
            seen.append(token)
    return seen[:20]


def extract_nights_mentions(text: str) -> list[int]:
    out: list[int] = []
    for m in NIGHTS_RE.finditer(text or ""):
        try:
            n = int(m.group(1))
        except ValueError:
            continue
        if n not in out:
            out.append(n)
    return out[:12]


def extract_duration_text(text: str) -> list[str]:
    seen: list[str] = []
    for m in NIGHTS_RE.finditer(text or ""):
        token = " ".join(m.group(0).split())
        if token not in seen:
            seen.append(token)
    return seen[:12]


def extract_totals(text: str) -> list[str]:
    seen: list[str] = []
    for m in CART_TOTAL_RE.finditer(text or ""):
        amt = m.group(1) or m.group(2)
        if not amt:
            continue
        token = f"${amt}"
        if token not in seen:
            seen.append(token)
    return seen[:8]


def goal_wants_deeper_walk(goal: str | None) -> bool:
    """True when the charter needs dates/week/cart, not just the first CTA."""
    return bool(GOAL_FOLLOWUP_RE.search(goal or ""))


def goal_asks_week(goal: str | None) -> bool:
    return bool(GOAL_WEEK_RE.search(goal or ""))


def next_saturday(today: date | None = None) -> date:
    d = today or date.today()
    ahead = (5 - d.weekday()) % 7
    return d + timedelta(days=ahead)


def sat_sat_iso(today: date | None = None) -> tuple[str, str]:
    """Delivery = next Saturday, pickup = Saturday+7, as ISO dates."""
    start = next_saturday(today)
    return start.isoformat(), (start + timedelta(days=7)).isoformat()


def is_followup_cta(text: str) -> bool:
    tl = (text or "").lower()
    return any(re.search(rf"\b{re.escape(w)}\b", tl) for w in FOLLOWUP_WORDS)


def choose_followup_cta(
    ctas: list[dict[str, Any]],
    *,
    already_clicked: str | None,
) -> dict[str, Any] | None:
    """Visible cart/setup/review after the first CTA. Never Pay/Send/Place order."""
    allowed = [
        c
        for c in ctas
        if c.get("visible")
        and is_followup_cta(str(c.get("text") or ""))
        and not is_forbidden_submit(str(c.get("text") or ""))
        and str(c.get("text") or "") != (already_clicked or "")
    ]
    if not allowed:
        return None

    def _rank(c: dict[str, Any]) -> tuple[int, str]:
        tl = str(c.get("text") or "").lower()
        order = 9
        for i, w in enumerate(FOLLOWUP_WORDS):
            if re.search(rf"\b{re.escape(w)}\b", tl):
                order = i
                break
        return (order, tl)

    allowed.sort(key=_rank)
    return allowed[0]


def assign_sat_sat_values(
    date_inputs: list[dict[str, Any]],
    start: str,
    end: str,
) -> list[tuple[dict[str, Any], str]]:
    visible = [
        d
        for d in date_inputs
        if d.get("visible") and not is_payment_field(str(d.get("name") or ""))
    ]
    if not visible:
        return []
    starts = [d for d in visible if START_DATE_NAME_RE.search(str(d.get("name") or ""))]
    ends = [d for d in visible if END_DATE_NAME_RE.search(str(d.get("name") or ""))]
    if starts and ends:
        return [(starts[0], start), (ends[0], end)]
    out: list[tuple[dict[str, Any], str]] = [(visible[0], start)]
    if len(visible) >= 2:
        out.append((visible[1], end))
    return out


def synthesize_stories(goal: str) -> list[Story]:
    """One charter story. The runner's explorer step does the walking."""
    _ = (goal or "").strip()
    return [Story(id="charter", steps=["explore"], expect="")]


def is_explore_step(step: str) -> bool:
    raw = (step or "").strip().lower()
    return raw == "explore" or raw.startswith("explore:")


def explore_goal_from_step(step: str, fallback: str | None) -> str | None:
    raw = (step or "").strip()
    if raw.lower().startswith("explore:") and raw.split(":", 1)[1].strip():
        return raw.split(":", 1)[1].strip()
    return fallback


def same_url(a: str | None, b: str | None) -> bool:
    def norm(u: str | None) -> str:
        parts = urlsplit(u or "")
        path = parts.path.rstrip("/") or "/"
        return urlunsplit((parts.scheme, parts.netloc.lower(), path, parts.query, ""))

    return norm(a) == norm(b)


def _body(page) -> str:
    try:
        return page.inner_text("body") or ""
    except Exception:
        return ""


def collect_ctas(page) -> list[dict[str, Any]]:
    try:
        raw = page.evaluate(CTA_JS)
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        out.append(
            {
                "text": text[:80],
                "tag": str(item.get("tag") or ""),
                "href": str(item.get("href") or "")[:240],
                "visible": bool(item.get("visible")),
                "type": str(item.get("type") or ""),
            }
        )
    return out


def collect_date_inputs(page) -> list[dict[str, Any]]:
    try:
        raw = page.evaluate(DATE_JS)
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "name": str(item.get("name") or "")[:80],
                "type": str(item.get("type") or ""),
                "value": str(item.get("value") or "")[:40],
                "visible": bool(item.get("visible")),
            }
        )
    return out[:20]


def collect_validation_messages(page) -> list[str]:
    try:
        raw = page.evaluate(VALIDATION_JS)
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        text = " ".join(str(item or "").split())
        if text and text not in out:
            out.append(text[:160])
    return out[:12]


def collect_page_observations(page, goal: str | None = None) -> dict[str, Any]:
    """Read-only snapshot: CTAs, prices, dates, validation. No clicks."""
    body = _body(page)
    ctas = collect_ctas(page)
    dates = collect_date_inputs(page)
    validation = collect_validation_messages(page)
    url = ""
    try:
        url = str(getattr(page, "url", "") or "")
    except Exception:
        url = ""
    primary = [
        {"text": c["text"], "href": c.get("href") or "", "visible": True}
        for c in ctas
        if c.get("visible") and is_primary_cta(c["text"])
    ]
    return {
        "ctas": primary,
        "clicked": None,
        "refused": [],
        "url": url,
        "url_before": url,
        "url_after": url,
        "same_url": True,
        "page_changed": False,
        "prices": extract_prices(body),
        "date_inputs": dates,
        "validation": validation,
        "nights_mentions": extract_nights_mentions(body),
        "duration_text": extract_duration_text(body),
        "totals": extract_totals(body),
        "dates_filled": [],
        "hidden_only_target": find_hidden_only_target(ctas, goal),
        "screenshot_before": None,
        "screenshot_after": None,
    }


def _prefer_visible(loc):
    filt = getattr(loc, "filter", None)
    if callable(filt):
        try:
            return loc.filter(visible=True)
        except TypeError:
            return loc
    return loc


def _click_visible_text(page, text: str, timeout: int = 5000) -> None:
    loc = page.get_by_text(text, exact=False)
    _prefer_visible(loc).first.click(timeout=timeout)


def _settle(page, extra_ms: int = 300) -> None:
    try:
        waiter = getattr(page, "wait_for_load_state", None)
        if callable(waiter):
            waiter("domcontentloaded", timeout=4000)
    except Exception:
        pass
    try:
        sleeper = getattr(page, "wait_for_timeout", None)
        if callable(sleeper):
            sleeper(extra_ms)
    except Exception:
        pass


def _page_url(page, fallback: str = "") -> str:
    try:
        return str(getattr(page, "url", "") or "") or fallback
    except Exception:
        return fallback


def _merge_unique(base: list, extra: list) -> list:
    out = list(base or [])
    for item in extra or []:
        if item not in out:
            out.append(item)
    return out


def _css_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _fill_date_field(page, item: dict[str, Any], value: str) -> None:
    name = str(item.get("name") or "")
    itype = str(item.get("type") or "")
    fill_val = value
    if itype == "datetime-local" and "T" not in fill_val:
        fill_val = fill_val + "T10:00"
    loc = None
    if name:
        esc = _css_quote(name)
        loc = page.locator(f'input[name="{esc}"], input[id="{esc}"]')
    elif itype:
        loc = page.locator(f'input[type="{itype}"]')
    else:
        loc = page.locator('input[type="date"], input[type="datetime-local"]')
    _prefer_visible(loc).first.fill(fill_val, timeout=4000)


def _apply_after_snapshot(obs: dict[str, Any], after: dict[str, Any]) -> None:
    obs["prices"] = _merge_unique(obs.get("prices") or [], after.get("prices") or [])
    obs["date_inputs"] = after.get("date_inputs") or []
    obs["validation"] = after.get("validation") or []
    obs["nights_mentions"] = _merge_unique(
        obs.get("nights_mentions") or [], after.get("nights_mentions") or []
    )
    obs["duration_text"] = _merge_unique(
        obs.get("duration_text") or [], after.get("duration_text") or []
    )
    obs["totals"] = _merge_unique(obs.get("totals") or [], after.get("totals") or [])
    obs["ctas"] = after.get("ctas") or obs.get("ctas") or []


def run_explorer(
    page,
    *,
    goal: str | None,
    job_id: str,
    story_id: str,
    vp_name: str,
    shot_root,
) -> tuple[dict[str, Any], str | None, str | None]:
    """Walk the charter. Returns (observations, action, error)."""
    url_before = _page_url(page)
    body_before = _body(page)
    shot_before = None
    try:
        name = f"{story_id}-{vp_name}-before.png"
        page.screenshot(path=str(shot_root / name), full_page=False)
        shot_before = f"reports/{job_id}/{name}"
    except Exception:
        shot_before = None

    ctas = collect_ctas(page)
    obs = collect_page_observations(page, goal)
    obs["url_before"] = url_before
    obs["screenshot_before"] = shot_before
    obs["refused"] = [
        {"text": c["text"], "reason": "submit/pay"}
        for c in ctas
        if c.get("visible") and is_forbidden_submit(c.get("text") or "")
    ]
    action_parts: list[str] = []

    chosen = choose_cta(ctas, goal or "")
    if chosen is None:
        action = None
        if obs["refused"] and not any(
            c.get("visible")
            and is_primary_cta(c.get("text") or "")
            and not is_forbidden_submit(c.get("text") or "")
            for c in ctas
        ):
            action = "refused submit/pay"
        obs["clicked"] = None
        obs["url_after"] = url_before
        obs["same_url"] = True
        obs["page_changed"] = False
        return obs, action, None

    try:
        _click_visible_text(page, chosen["text"], timeout=5000)
        action_parts.append(f"clicked {chosen['text']}")
        obs["clicked"] = {"text": chosen["text"], "href": chosen.get("href") or ""}
    except Exception as exc:  # noqa: BLE001
        obs["clicked"] = None
        return obs, None, f"step failed (explore click {chosen['text'][:40]}): {exc}"

    _settle(page)
    url_after_first = _page_url(page, url_before)
    body_after_first = _body(page)
    obs["same_url"] = same_url(url_before, url_after_first)
    obs["page_changed"] = (not obs["same_url"]) or (
        body_after_first.strip() != body_before.strip()
    )

    if goal_wants_deeper_walk(goal):
        follow_ctas = collect_ctas(page)
        follow = choose_followup_cta(follow_ctas, already_clicked=chosen["text"])
        if follow is not None:
            try:
                _click_visible_text(page, follow["text"], timeout=5000)
                action_parts.append(f"clicked {follow['text']}")
                obs["clicked_followup"] = {
                    "text": follow["text"],
                    "href": follow.get("href") or "",
                }
                _settle(page)
            except Exception:
                obs["clicked_followup"] = None
        extra_refused = [
            {"text": c["text"], "reason": "submit/pay"}
            for c in follow_ctas
            if c.get("visible") and is_forbidden_submit(c.get("text") or "")
        ]
        obs["refused"] = _merge_unique(obs.get("refused") or [], extra_refused)

    after_walk = collect_page_observations(page, goal)
    _apply_after_snapshot(obs, after_walk)

    dates_filled: list[dict[str, str]] = []
    if goal_asks_week(goal):
        start, end = sat_sat_iso()
        pairs = assign_sat_sat_values(obs.get("date_inputs") or [], start, end)
        for item, value in pairs:
            try:
                _fill_date_field(page, item, value)
                name = str(item.get("name") or item.get("type") or "date")
                dates_filled.append({"name": name, "value": value})
                action_parts.append(f"filled {name}={value}")
            except Exception:
                continue
        if dates_filled:
            _settle(page, extra_ms=400)
            after_fill = collect_page_observations(page, goal)
            _apply_after_snapshot(obs, after_fill)

    obs["dates_filled"] = dates_filled
    obs["url_after"] = _page_url(page, url_after_first)
    final_ctas = collect_ctas(page)
    obs["refused"] = _merge_unique(
        obs.get("refused") or [],
        [
            {"text": c["text"], "reason": "submit/pay"}
            for c in final_ctas
            if c.get("visible") and is_forbidden_submit(c.get("text") or "")
        ],
    )

    try:
        name = f"{story_id}-{vp_name}-after.png"
        page.screenshot(path=str(shot_root / name), full_page=False)
        obs["screenshot_after"] = f"reports/{job_id}/{name}"
    except Exception:
        obs["screenshot_after"] = None

    return obs, "; ".join(action_parts) if action_parts else None, None

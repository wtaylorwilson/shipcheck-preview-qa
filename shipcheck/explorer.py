"""Deterministic charter explorer (v0). No LLM, no extra keys.

Given a public URL + goal text, collect visible primary CTAs, click the
most relevant one once (visible-first), screenshot before/after, and
record prices / date inputs / validation. Never fill payment fields.
Never submit Send / Submit request / Pay / Place order.
"""

from __future__ import annotations

import re
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
        "hidden_only_target": find_hidden_only_target(ctas, goal),
        "screenshot_before": None,
        "screenshot_after": None,
    }


def _click_visible_text(page, text: str, timeout: int = 5000) -> None:
    loc = page.get_by_text(text, exact=False)
    filt = getattr(loc, "filter", None)
    if callable(filt):
        try:
            loc = loc.filter(visible=True)
        except TypeError:
            pass
    loc.first.click(timeout=timeout)


def run_explorer(
    page,
    *,
    goal: str | None,
    job_id: str,
    story_id: str,
    vp_name: str,
    shot_root,
) -> tuple[dict[str, Any], str | None, str | None]:
    """Walk once. Returns (observations, action, error)."""
    url_before = ""
    try:
        url_before = str(getattr(page, "url", "") or "")
    except Exception:
        url_before = ""
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
        action = f"clicked {chosen['text']}"
        obs["clicked"] = {"text": chosen["text"], "href": chosen.get("href") or ""}
    except Exception as exc:  # noqa: BLE001
        obs["clicked"] = None
        return obs, None, f"step failed (explore click {chosen['text'][:40]}): {exc}"

    try:
        waiter = getattr(page, "wait_for_load_state", None)
        if callable(waiter):
            waiter("domcontentloaded", timeout=4000)
    except Exception:
        pass
    try:
        sleeper = getattr(page, "wait_for_timeout", None)
        if callable(sleeper):
            sleeper(300)
    except Exception:
        pass

    url_after = ""
    try:
        url_after = str(getattr(page, "url", "") or "")
    except Exception:
        url_after = url_before
    body_after = _body(page)
    after = collect_page_observations(page, goal)
    obs["url_after"] = url_after
    obs["same_url"] = same_url(url_before, url_after)
    obs["page_changed"] = (not obs["same_url"]) or (body_after.strip() != body_before.strip())
    obs["prices"] = after.get("prices") or obs.get("prices") or []
    obs["date_inputs"] = after.get("date_inputs") or []
    obs["validation"] = after.get("validation") or []
    obs["nights_mentions"] = after.get("nights_mentions") or []
    obs["ctas"] = after.get("ctas") or obs.get("ctas") or []

    try:
        name = f"{story_id}-{vp_name}-after.png"
        page.screenshot(path=str(shot_root / name), full_page=False)
        obs["screenshot_after"] = f"reports/{job_id}/{name}"
    except Exception:
        obs["screenshot_after"] = None

    return obs, action, None

"""Billing hook.

v0 does not charge. Polar/Stripe prepaid credits plug in here later:

1. Operator buys a credit pack; Polar mints a license key used as the API key.
2. POST /qa_preview reads Authorization: Bearer <key>.
3. On *successful completion* (pass or needs_review), debit $6 or $10.
   Timeouts, SSRF rejects, and Playwright crashes are not billed.
4. Idempotency key is the job_id so agent retries are free.

Do not build a dashboard or a custom ledger in this file.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DebitResult:
    ok: bool
    billed: bool
    remaining: float | None
    reason: str
    price_usd: int


def price_usd(viewport: str, n_stories: int) -> int:
    """$6 desktop (or mobile), $10 both-viewports or 5–8 stories."""
    if viewport == "both" or n_stories >= 5:
        return 10
    return 6


def extract_api_key(authorization: str | None, x_api_key: str | None) -> str | None:
    if x_api_key:
        return x_api_key.strip() or None
    if authorization:
        parts = authorization.strip().split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip() or None
        return authorization.strip() or None
    return None


def check_api_key(api_key: str | None) -> tuple[bool, str]:
    """v0: keys are optional and always accepted. Later: Polar license lookup."""
    return True, "v0_open"


def debit(
    api_key: str | None,
    job_id: str,
    viewport: str,
    n_stories: int,
) -> DebitResult:
    """No-op debit. Wire Polar increment_usage (or Stripe) here.

    `job_id` is the idempotency key. Only call this after the runner finishes
    without an infrastructure error.
    """
    price = price_usd(viewport, n_stories)
    _ = (api_key, job_id)
    return DebitResult(
        ok=True,
        billed=False,
        remaining=None,
        reason="v0_billing_disabled",
        price_usd=price,
    )

"""Shared QA operations used by REST and MCP. Does not run Playwright."""

from __future__ import annotations

from typing import Any

from shipcheck.billing import check_api_key, price_usd
from shipcheck.models import QaNoteRequest, QaPreviewRequest, public_job
from shipcheck.ratelimit import consume_preview_slot
from shipcheck.ssrf import UnsafeUrl, assert_url_allowed
from shipcheck.store import create_job, load_job, save_job, utcnow


class ServiceError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def enqueue_preview(
    body: QaPreviewRequest,
    api_key: str | None,
    client_ip: str | None = None,
) -> dict[str, Any]:
    ok, reason = check_api_key(api_key)
    if not ok:
        raise ServiceError(401, reason)

    try:
        assert_url_allowed(body.url, resolve=True)
    except UnsafeUrl as exc:
        raise ServiceError(400, f"unsafe url: {exc}") from exc

    if body.webhook_url:
        try:
            assert_url_allowed(body.webhook_url, resolve=True)
        except UnsafeUrl as exc:
            raise ServiceError(400, f"unsafe webhook_url: {exc}") from exc

    ok, reason = consume_preview_slot(client_ip)
    if not ok:
        raise ServiceError(429, reason)

    n = len(body.stories)
    price = price_usd(body.viewport, n)
    job = create_job(
        {
            "url": body.url,
            "stories": [s.model_dump() for s in body.stories],
            "viewport": body.viewport,
            "auth_hint": body.auth_hint,
            "webhook_url": body.webhook_url,
            "price_usd": price,
            "billing_reason": "v0_billing_disabled",
        }
    )
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "price_usd": price,
        "billed": False,
        "message": (
            "queued. poll qa_status / GET /qa_status/{job_id}; "
            "fetch qa_get_report / GET /qa_get_report/{job_id} when status is pass or needs_review."
        ),
    }


def _require_job(job_id: str) -> dict[str, Any]:
    jid = (job_id or "").strip()
    if not (4 <= len(jid) <= 40):
        raise ServiceError(400, "invalid job_id")
    job = load_job(jid)
    if not job:
        raise ServiceError(404, "unknown job_id")
    return job


def get_status(job_id: str) -> dict[str, Any]:
    return public_job(_require_job(job_id), include_report=False)


def get_report(job_id: str) -> dict[str, Any]:
    return public_job(_require_job(job_id), include_report=True)


def add_note(job_id: str, body: QaNoteRequest) -> dict[str, Any]:
    job = _require_job(job_id)
    if job.get("status") != "needs_review":
        raise ServiceError(
            409,
            f"job is {job.get('status')}, notes only apply to needs_review",
        )
    job["human_note"] = body.human_note
    job["human_verdict"] = body.verdict
    job["reviewed_at"] = utcnow()
    if body.verdict == "pass":
        job["status"] = "pass"
    save_job(job)
    return public_job(job, include_report=True)

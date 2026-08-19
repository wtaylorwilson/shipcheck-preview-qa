from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Viewport = Literal["desktop", "mobile", "both"]
JobStatus = Literal["queued", "running", "pass", "needs_review", "error"]
NoteVerdict = Literal["pass", "fail"]


class Story(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    steps: list[str] = Field(default_factory=list, max_length=20)
    expect: str | list[str] = ""

    @field_validator("id")
    @classmethod
    def _id_safe(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("story id is required")
        # Screenshot filenames use this id.
        for ch in cleaned:
            if not (ch.isalnum() or ch in ("-", "_", ".")):
                raise ValueError("story id may contain letters, digits, - _ . only")
        return cleaned


class QaPreviewRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    stories: list[Story] = Field(min_length=1, max_length=8)
    viewport: Viewport = "desktop"
    auth_hint: str | None = Field(default=None, max_length=200)
    webhook_url: str | None = None

    @field_validator("url")
    @classmethod
    def _strip_url(cls, v: str) -> str:
        return v.strip()


class QaPreviewResponse(BaseModel):
    job_id: str
    status: JobStatus
    price_usd: int
    billed: bool = False
    message: str


class QaNoteRequest(BaseModel):
    human_note: str = Field(min_length=1, max_length=4000)
    verdict: NoteVerdict

    @field_validator("human_note")
    @classmethod
    def _strip_note(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("human_note is required")
        return cleaned


class HealthResponse(BaseModel):
    ok: bool
    service: str
    version: str


def expect_list(expect: str | list[str]) -> list[str]:
    if isinstance(expect, list):
        return [e for e in (x.strip() for x in expect) if e]
    e = (expect or "").strip()
    return [e] if e else []


def public_job(job: dict[str, Any], *, include_report: bool = False) -> dict[str, Any]:
    out = {
        "job_id": job["job_id"],
        "status": job["status"],
        "url": job.get("url"),
        "viewport": job.get("viewport"),
        "price_usd": job.get("price_usd"),
        "billed": job.get("billed", False),
        "created_at": job.get("created_at"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "error": job.get("error"),
    }
    if include_report:
        out["report"] = job.get("report")
        out["human_note"] = job.get("human_note")
        out["human_verdict"] = job.get("human_verdict")
    return out

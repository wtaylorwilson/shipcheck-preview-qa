"""On-disk job queue and reports. One JSON file per job, flock for workers."""

from __future__ import annotations

import fcntl
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from shipcheck.paths import QUEUE_DIR, REPORTS_DIR, ensure_dirs

ISO = "%Y-%m-%dT%H:%M:%SZ"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime(ISO)


def new_job_id() -> str:
    return "sc_" + uuid.uuid4().hex[:12]


def queue_path(job_id: str) -> Path:
    return QUEUE_DIR / f"{job_id}.json"


def report_path(job_id: str) -> Path:
    return REPORTS_DIR / f"{job_id}.json"


def screenshot_dir(job_id: str) -> Path:
    return REPORTS_DIR / job_id


@contextmanager
def _locked(path: Path, create: bool = False) -> Iterator[Any]:
    ensure_dirs()
    mode = "r+" if path.exists() else "w+"
    if not create and not path.exists():
        raise FileNotFoundError(path)
    fd = open(path, mode)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield fd
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()


def _read(fd) -> dict[str, Any]:
    fd.seek(0)
    raw = fd.read()
    if not raw.strip():
        return {}
    return json.loads(raw)


def _write(fd, data: dict[str, Any]) -> None:
    fd.seek(0)
    json.dump(data, fd, indent=2, sort_keys=False)
    fd.write("\n")
    fd.truncate()
    fd.flush()
    os.fsync(fd.fileno())


def create_job(payload: dict[str, Any]) -> dict[str, Any]:
    ensure_dirs()
    job_id = new_job_id()
    job = {
        "job_id": job_id,
        "status": "queued",
        "created_at": utcnow(),
        "started_at": None,
        "finished_at": None,
        "url": payload["url"],
        "stories": payload["stories"],
        "viewport": payload["viewport"],
        "auth_hint": payload.get("auth_hint"),
        "webhook_url": payload.get("webhook_url"),
        "price_usd": payload["price_usd"],
        "billed": False,
        "billing_reason": payload.get("billing_reason", "v0_billing_disabled"),
        "human_note": None,
        "error": None,
        "report": None,
    }
    path = queue_path(job_id)
    with _locked(path, create=True) as fd:
        _write(fd, job)
    return job


def load_job(job_id: str) -> dict[str, Any] | None:
    path = queue_path(job_id)
    if not path.exists():
        # Finished jobs still live in queue/; reports are a copy.
        rpath = report_path(job_id)
        if rpath.exists():
            return json.loads(rpath.read_text())
        return None
    with _locked(path) as fd:
        return _read(fd)


def save_job(job: dict[str, Any]) -> dict[str, Any]:
    path = queue_path(job["job_id"])
    with _locked(path, create=True) as fd:
        _write(fd, job)
    # Mirror a report snapshot whenever we have a terminal or running result.
    if job.get("status") in ("pass", "needs_review", "error", "running"):
        rpath = report_path(job["job_id"])
        rpath.write_text(json.dumps(job, indent=2) + "\n")
    return job


def claim_next() -> dict[str, Any] | None:
    """Atomically mark the oldest queued job as running and return it."""
    ensure_dirs()
    files = sorted(QUEUE_DIR.glob("sc_*.json"), key=lambda p: p.stat().st_mtime)
    for path in files:
        with _locked(path) as fd:
            job = _read(fd)
            if job.get("status") != "queued":
                continue
            job["status"] = "running"
            job["started_at"] = utcnow()
            _write(fd, job)
            return job
    return None


def list_queued() -> list[str]:
    ensure_dirs()
    out = []
    for path in sorted(QUEUE_DIR.glob("sc_*.json")):
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        if data.get("status") == "queued":
            out.append(data["job_id"])
    return out

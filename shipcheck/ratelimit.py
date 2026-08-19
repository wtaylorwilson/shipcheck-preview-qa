"""Per-IP daily cap on preview jobs so a public URL is not a screenshot farm."""

from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime, timezone
from ipaddress import ip_address
from typing import Any

from shipcheck.paths import HOME, ensure_dirs

DEFAULT_LIMIT = 20
STORE = HOME / "ratelimit.json"

_UNLIMITED_HOSTS = frozenset(
    {"127.0.0.1", "::1", "localhost", "testclient", "unknown", ""}
)


def daily_limit() -> int:
    raw = os.environ.get("SHIPCHECK_PREVIEW_LIMIT_PER_IP", str(DEFAULT_LIMIT)).strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_LIMIT


def utc_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def is_unlimited(ip: str | None) -> bool:
    if ip is None:
        return True
    host = ip.strip().lower().split("%")[0]
    if host in _UNLIMITED_HOSTS:
        return True
    try:
        return bool(ip_address(host).is_loopback)
    except ValueError:
        return False


def client_ip(headers: dict[str, str] | None, peer: str | None) -> str:
    """Prefer Cloudflare / proxy headers; fall back to the socket peer."""
    h = {k.lower(): v for k, v in (headers or {}).items()}
    cf = (h.get("cf-connecting-ip") or "").strip()
    if cf:
        return cf.split(",")[0].strip()
    xff = (h.get("x-forwarded-for") or "").strip()
    if xff:
        return xff.split(",")[0].strip()
    return (peer or "unknown").strip()


def _read(fd) -> dict[str, Any]:
    fd.seek(0)
    raw = fd.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def consume_preview_slot(ip: str | None) -> tuple[bool, str]:
    """Record one preview job. Returns (ok, reason). Loopback is unlimited."""
    limit = daily_limit()
    if limit <= 0 or is_unlimited(ip):
        return True, ""

    key = (ip or "unknown").strip() or "unknown"
    day = utc_day()
    ensure_dirs()
    path = STORE
    mode = "r+" if path.exists() else "w+"
    with open(path, mode) as fd:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            data = _read(fd)
            bucket = data.get(day)
            if not isinstance(bucket, dict):
                # Drop other days so the file stays small.
                bucket = {}
                data = {day: bucket}
            used = int(bucket.get(key, 0) or 0)
            if used >= limit:
                return False, (
                    f"rate limit: {limit} preview jobs/day/IP. "
                    "try again tomorrow (UTC) or wait for credits."
                )
            bucket[key] = used + 1
            data[day] = bucket
            fd.seek(0)
            json.dump(data, fd, indent=2)
            fd.write("\n")
            fd.truncate()
            fd.flush()
            os.fsync(fd.fileno())
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    return True, ""

"""REST + streamable-HTTP MCP. Other coding agents call either surface."""

from __future__ import annotations

import os
import threading
import time
from contextlib import asynccontextmanager
from typing import Any

from pathlib import Path as _Path

from fastapi import FastAPI, Header, HTTPException, Path, Request
from starlette.responses import HTMLResponse, Response

from shipcheck import __version__
from shipcheck.billing import extract_api_key
from shipcheck.mcp import dispatch_mcp
from shipcheck.models import QaNoteRequest, QaPreviewRequest
from shipcheck.ratelimit import client_ip
from shipcheck.service import ServiceError, add_note, enqueue_preview, get_report, get_status

_LANDING = _Path(__file__).with_name("landing.html")


def _maybe_start_inline_worker() -> None:
    flag = os.environ.get("SHIPCHECK_INLINE_WORKER", "1").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return

    def loop() -> None:
        # Imported lazily so `import server` in tests does not need Playwright
        # until a job is actually claimed.
        from shipcheck.cli import drain_once

        while True:
            try:
                did = drain_once()
                if not did:
                    time.sleep(1.0)
            except Exception:
                time.sleep(2.0)

    t = threading.Thread(target=loop, name="shipcheck-worker", daemon=True)
    t.start()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _maybe_start_inline_worker()
    yield


app = FastAPI(
    title="ShipCheck",
    version=__version__,
    description=(
        "Independent preview-URL QA. REST or streamable-HTTP MCP at POST /mcp "
        "with qa_preview, qa_status, qa_get_report, qa_note."
    ),
    lifespan=lifespan,
)


def _http(exc: ServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
def landing() -> HTMLResponse:
    return HTMLResponse(_LANDING.read_text(encoding="utf-8"))


@app.api_route("/health", methods=["GET", "HEAD"])
def health() -> dict[str, Any]:
    return {"ok": True, "service": "shipcheck", "version": __version__, "mcp": True}


@app.post("/qa_preview")
def qa_preview(
    body: QaPreviewRequest,
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
) -> dict[str, Any]:
    api_key = extract_api_key(authorization, x_api_key)
    ip = client_ip(dict(request.headers), request.client.host if request.client else None)
    try:
        return enqueue_preview(body, api_key, client_ip=ip)
    except ServiceError as exc:
        raise _http(exc) from exc


@app.get("/qa_status/{job_id}")
def qa_status(job_id: str = Path(min_length=4, max_length=40)) -> dict[str, Any]:
    try:
        return get_status(job_id)
    except ServiceError as exc:
        raise _http(exc) from exc


@app.get("/qa_get_report/{job_id}")
def qa_get_report(job_id: str = Path(min_length=4, max_length=40)) -> dict[str, Any]:
    try:
        return get_report(job_id)
    except ServiceError as exc:
        raise _http(exc) from exc


@app.post("/qa_note/{job_id}")
def qa_note(
    body: QaNoteRequest,
    job_id: str = Path(min_length=4, max_length=40),
) -> dict[str, Any]:
    try:
        return add_note(job_id, body)
    except ServiceError as exc:
        raise _http(exc) from exc


@app.api_route("/mcp", methods=["GET", "POST", "DELETE", "OPTIONS"], include_in_schema=True)
async def mcp_endpoint(request: Request) -> Response:
    """Streamable-HTTP MCP (JSON-RPC 2.0). Same tools as the REST routes."""
    return await dispatch_mcp(request)


def create_app() -> FastAPI:
    return app

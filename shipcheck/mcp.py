"""Streamable-HTTP MCP (JSON-RPC 2.0) at POST /mcp.

A correct minimal implementation so we keep FastAPI's existing lifespan
(inline worker) and serve REST + MCP on the same process. Official SDK
mounting wants its own session-manager lifespan and historically lands
on /mcp/mcp; not worth the fight for three tools.

Transport: Streamable HTTP (2025-03-26). Stateless JSON responses by
default; SSE when the client only accepts text/event-stream. GET is 405
(no server-initiated stream). Sessions are not required.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from shipcheck import __version__
from shipcheck.billing import extract_api_key
from shipcheck.models import QaNoteRequest, QaPreviewRequest
from shipcheck.service import ServiceError, add_note, enqueue_preview, get_report, get_status

PROTOCOL_DEFAULT = "2025-03-26"
PROTOCOL_SUPPORTED = frozenset(
    {
        "2024-11-05",
        "2025-03-26",
        "2025-06-18",
        "2025-11-25",
        "2026-07-28",
    }
)

JSONRPC_PARSE = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL = -32603

_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

_CORS_HEADERS = (
    "Content-Type, Accept, Authorization, X-Api-Key, Mcp-Session-Id, MCP-Protocol-Version"
)

TOOLS: list[dict[str, Any]] = [
    {
        "name": "qa_preview",
        "description": (
            "Queue an independent Playwright QA run against a public https preview URL. "
            "Pass click:/fill:/see: stories, or a goal/charter (human-equivalent QA) "
            "and we synthesize an explorer walk. Homepage expect-only is smoke "
            "(needs_review, not pass). Returns a job_id. Poll qa_status; fetch "
            "qa_get_report when status is pass or needs_review. Report includes "
            "human_note and findings[]. https only; localhost and private IPs are rejected."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "minLength": 8,
                    "maxLength": 2048,
                    "description": "Public https preview URL",
                },
                "goal": {
                    "type": "string",
                    "maxLength": 500,
                    "description": (
                        "Charter for human-equivalent QA, e.g. "
                        "'Walk booking and check a Sat-Sat week uses the weekly rate'. "
                        "If stories are omitted, a built-in explorer synthesizes them."
                    ),
                },
                "charter": {
                    "type": "string",
                    "maxLength": 500,
                    "description": "Alias for goal",
                },
                "stories": {
                    "type": "array",
                    "minItems": 0,
                    "maxItems": 8,
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "Story id (letters, digits, - _ .)",
                            },
                            "steps": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "Optional: click:css=.buy, click:text=Sign in, "
                                    "fill:#email|user@example.com, wait:1000, see:Order total"
                                ),
                            },
                            "expect": {
                                "description": "Visible text that must appear",
                                "oneOf": [
                                    {"type": "string"},
                                    {"type": "array", "items": {"type": "string"}},
                                ],
                            },
                        },
                        "required": ["id"],
                    },
                },
                "viewport": {
                    "type": "string",
                    "enum": ["desktop", "mobile", "both"],
                    "default": "desktop",
                },
                "auth_hint": {
                    "type": "string",
                    "maxLength": 200,
                    "description": "Public demo credentials only; not used to log in in v0",
                },
                "webhook_url": {
                    "type": "string",
                    "description": "Accepted and SSRF-checked; not fired in v0",
                },
            },
            "required": ["url"],
            "additionalProperties": False,
        },
        "annotations": {
            "title": "QA preview",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    },
    {
        "name": "qa_status",
        "description": "Poll a ShipCheck job: queued / running / pass / needs_review / error.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "minLength": 4, "maxLength": 40},
            },
            "required": ["job_id"],
            "additionalProperties": False,
        },
        "annotations": {
            "title": "QA status",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
    {
        "name": "qa_get_report",
        "description": (
            "Evidence pack for a job: heuristics, screenshot paths, human_note "
            "(always written after heuristics), and findings[{severity,title,detail}]. "
            "Call when qa_status is pass or needs_review."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "minLength": 4, "maxLength": 40},
            },
            "required": ["job_id"],
            "additionalProperties": False,
        },
        "annotations": {
            "title": "QA report",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
    {
        "name": "qa_note",
        "description": (
            "Close a needs_review job with a human/agent note. "
            "verdict=pass promotes status to pass; verdict=fail keeps needs_review."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "minLength": 4, "maxLength": 40},
                "human_note": {"type": "string", "minLength": 1, "maxLength": 4000},
                "verdict": {"type": "string", "enum": ["pass", "fail"]},
            },
            "required": ["job_id", "human_note", "verdict"],
            "additionalProperties": False,
        },
        "annotations": {
            "title": "QA note",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    },
]


def _origin_host(origin: str) -> str | None:
    try:
        parsed = urlparse(origin)
    except Exception:
        return None
    host = (parsed.hostname or "").lower()
    return host or None


def origin_allowed(origin: str | None, host_header: str | None) -> bool:
    """DNS-rebinding guard. Missing Origin (curl / Cursor) is allowed."""
    if not origin:
        return True
    oh = _origin_host(origin)
    if not oh:
        return False
    if oh in _LOCAL_HOSTS:
        return True
    if host_header:
        hh = host_header.split("@")[-1].split(":")[0].lower().strip("[]")
        if oh == hh:
            return True
    return False


def _cors(origin: str | None) -> dict[str, str]:
    headers = {
        "Access-Control-Allow-Methods": "POST, GET, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": _CORS_HEADERS,
        "Access-Control-Expose-Headers": "Mcp-Session-Id, MCP-Protocol-Version",
        "Access-Control-Max-Age": "86400",
    }
    if origin:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Vary"] = "Origin"
    return headers


def _rpc_error(id_: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": id_, "error": err}


def _rpc_result(id_: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _tool_payload(data: Any, *, is_error: bool = False) -> dict[str, Any]:
    if isinstance(data, str):
        text = data
        structured = None
    else:
        text = json.dumps(data, indent=2)
        structured = data
    out: dict[str, Any] = {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }
    if structured is not None:
        out["structuredContent"] = structured
    return out


def _call_tool(
    name: str,
    arguments: dict[str, Any],
    api_key: str | None,
    client_ip: str | None = None,
) -> dict[str, Any]:
    if name == "qa_preview":
        body = QaPreviewRequest.model_validate(arguments)
        return _tool_payload(enqueue_preview(body, api_key, client_ip=client_ip))
    if name == "qa_status":
        return _tool_payload(get_status(str(arguments.get("job_id") or "")))
    if name == "qa_get_report":
        return _tool_payload(get_report(str(arguments.get("job_id") or "")))
    if name == "qa_note":
        job_id = str(arguments.get("job_id") or "")
        note = QaNoteRequest.model_validate(
            {
                "human_note": arguments.get("human_note"),
                "verdict": arguments.get("verdict"),
            }
        )
        return _tool_payload(add_note(job_id, note))
    raise KeyError(name)


def _handle_method(method: str, params: Any, api_key: str | None, client_ip: str | None = None) -> Any:
    params = params or {}
    if not isinstance(params, dict):
        raise TypeError("params must be an object")

    if method == "initialize":
        requested = params.get("protocolVersion") or PROTOCOL_DEFAULT
        chosen = requested if requested in PROTOCOL_SUPPORTED else PROTOCOL_DEFAULT
        return {
            "protocolVersion": chosen,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "shipcheck", "version": __version__},
            "instructions": (
                "Independent preview-URL QA. Call qa_preview with a public https URL and "
                "either click:/fill:/see: stories or a goal/charter (explorer synthesizes "
                "the walk). Homepage expect-only is smoke, not a pass. "
                "poll qa_status, then qa_get_report for human_note + findings[]. "
                "On needs_review, qa_note can attach a later human/agent verdict."
            ),
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name = params.get("name")
        if not name:
            raise ValueError("tools/call requires name")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be an object")
        return _call_tool(str(name), arguments, api_key, client_ip=client_ip)
    if method in ("resources/list", "resources/templates/list", "prompts/list"):
        key = {
            "resources/list": "resources",
            "resources/templates/list": "resourceTemplates",
            "prompts/list": "prompts",
        }[method]
        return {key: []}
    raise LookupError(method)


def handle_rpc_message(msg: Any, api_key: str | None, client_ip: str | None = None) -> dict[str, Any] | None:
    """Return a JSON-RPC response dict, or None for a notification."""
    if not isinstance(msg, dict):
        return _rpc_error(None, JSONRPC_INVALID_REQUEST, "Request must be an object")
    if msg.get("jsonrpc") != "2.0":
        return _rpc_error(msg.get("id"), JSONRPC_INVALID_REQUEST, "jsonrpc must be 2.0")

    # Client → server response (we never send server requests)
    if "result" in msg or "error" in msg:
        return None

    method = msg.get("method")
    if not isinstance(method, str) or not method:
        return _rpc_error(msg.get("id"), JSONRPC_INVALID_REQUEST, "method is required")

    is_notification = "id" not in msg
    if method.startswith("notifications/"):
        return None

    try:
        result = _handle_method(method, msg.get("params"), api_key, client_ip=client_ip)
    except LookupError:
        if is_notification:
            return None
        return _rpc_error(msg.get("id"), JSONRPC_METHOD_NOT_FOUND, f"Method not found: {method}")
    except KeyError:
        return _rpc_error(msg.get("id"), JSONRPC_INVALID_PARAMS, f"Unknown tool: {method}")
    except (ValidationError, ValueError, TypeError, ServiceError) as exc:
        if is_notification:
            return None
        if isinstance(exc, ServiceError):
            # Application errors belong in the tool result so the model can read them.
            if method == "tools/call":
                return _rpc_result(msg.get("id"), _tool_payload(exc.detail, is_error=True))
            return _rpc_error(msg.get("id"), JSONRPC_INVALID_PARAMS, exc.detail)
        if method == "tools/call" and isinstance(exc, (ValidationError, ValueError)):
            return _rpc_result(msg.get("id"), _tool_payload(str(exc), is_error=True))
        return _rpc_error(msg.get("id"), JSONRPC_INVALID_PARAMS, str(exc))
    except Exception as exc:  # noqa: BLE001
        if is_notification:
            return None
        return _rpc_error(msg.get("id"), JSONRPC_INTERNAL, "internal error", data=str(exc))

    if is_notification:
        return None
    return _rpc_result(msg.get("id"), result)


def _wants_sse(accept: str) -> bool:
    accept_l = (accept or "").lower()
    has_sse = "text/event-stream" in accept_l
    has_json = "application/json" in accept_l
    return has_sse and not has_json


def _sse_body(payload: Any) -> bytes:
    frames: list[str] = []
    if isinstance(payload, list):
        items = payload
    else:
        items = [payload]
    for i, item in enumerate(items, start=1):
        data = json.dumps(item, separators=(",", ":"))
        frames.append(f"id: {i}\nevent: message\ndata: {data}\n\n")
    return "".join(frames).encode("utf-8")


async def dispatch_mcp(request: Request) -> Response:
    origin = request.headers.get("origin")
    host = request.headers.get("host")
    cors = _cors(origin)

    if not origin_allowed(origin, host):
        return JSONResponse(
            {"error": "origin not allowed"},
            status_code=403,
            headers=cors,
        )

    if request.method == "OPTIONS":
        return Response(status_code=204, headers=cors)

    if request.method in ("GET", "DELETE"):
        headers = {"Allow": "POST, OPTIONS", **cors}
        return Response(status_code=405, headers=headers)

    if request.method != "POST":
        return Response(status_code=405, headers={"Allow": "POST, OPTIONS", **cors})

    raw = await request.body()
    if not raw.strip():
        return JSONResponse(
            _rpc_error(None, JSONRPC_PARSE, "Parse error: empty body"),
            status_code=400,
            headers=cors,
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return JSONResponse(
            _rpc_error(None, JSONRPC_PARSE, "Parse error"),
            status_code=400,
            headers=cors,
        )

    from shipcheck.ratelimit import client_ip as _client_ip

    api_key = extract_api_key(
        request.headers.get("authorization"),
        request.headers.get("x-api-key"),
    )
    peer = request.client.host if request.client else None
    ip = _client_ip(dict(request.headers), peer)

    batch = isinstance(payload, list)
    messages = payload if batch else [payload]
    if batch and not messages:
        return JSONResponse(
            _rpc_error(None, JSONRPC_INVALID_REQUEST, "empty batch"),
            status_code=400,
            headers=cors,
        )

    responses: list[dict[str, Any]] = []
    for msg in messages:
        # Unknown tool is a KeyError from _call_tool; remap to protocol error.
        if (
            isinstance(msg, dict)
            and msg.get("method") == "tools/call"
            and isinstance(msg.get("params"), dict)
        ):
            tname = msg["params"].get("name")
            known = {t["name"] for t in TOOLS}
            if tname and tname not in known:
                responses.append(
                    _rpc_error(msg.get("id"), JSONRPC_INVALID_PARAMS, f"Unknown tool: {tname}")
                )
                continue
        out = handle_rpc_message(msg, api_key, client_ip=ip)
        if out is not None:
            responses.append(out)

    if not responses:
        return Response(status_code=202, headers=cors)

    body: Any = responses if batch else responses[0]
    if _wants_sse(request.headers.get("accept") or ""):
        return Response(
            content=_sse_body(body),
            status_code=200,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", **cors},
        )
    return JSONResponse(body, headers=cors)

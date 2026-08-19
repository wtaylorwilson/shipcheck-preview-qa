from __future__ import annotations

import json
import os

os.environ["SHIPCHECK_INLINE_WORKER"] = "0"
os.environ.setdefault("SHIPCHECK_HOME", "/workspace/shipcheck")

from fastapi.testclient import TestClient

from shipcheck.server import app

client = TestClient(app)

ACCEPT = "application/json, text/event-stream"


def _rpc(method: str, params: dict | None = None, id_: int = 1, **kwargs):
    payload = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        payload["params"] = params
    headers = {"Accept": ACCEPT, **kwargs.pop("headers", {})}
    return client.post("/mcp", json=payload, headers=headers, **kwargs)


def test_mcp_initialize() -> None:
    r = _rpc(
        "initialize",
        {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "0"},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == 1
    result = body["result"]
    assert result["protocolVersion"] in {"2025-03-26", "2024-11-05", "2025-06-18"}
    assert "tools" in result["capabilities"]
    assert result["serverInfo"]["name"] == "shipcheck"


def test_mcp_initialized_notification_is_202() -> None:
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        headers={"Accept": ACCEPT},
    )
    assert r.status_code == 202
    assert r.content in (b"", b"null")


def test_mcp_tools_list() -> None:
    r = _rpc("tools/list", {}, id_=2)
    assert r.status_code == 200, r.text
    tools = r.json()["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {"qa_preview", "qa_status", "qa_get_report"} <= names
    preview = next(t for t in tools if t["name"] == "qa_preview")
    assert "url" in preview["inputSchema"]["properties"]
    assert "stories" in preview["inputSchema"]["required"]


def test_mcp_qa_preview_happy_path() -> None:
    r = _rpc(
        "tools/call",
        {
            "name": "qa_preview",
            "arguments": {
                "url": "https://example.com/",
                "stories": [
                    {"id": "home", "steps": ["open"], "expect": "Example Domain"}
                ],
                "viewport": "desktop",
            },
        },
        id_=3,
    )
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert result["isError"] is False
    text = result["content"][0]["text"]
    payload = json.loads(text)
    assert payload["status"] == "queued"
    assert payload["job_id"].startswith("sc_")
    assert payload["price_usd"] == 6
    job_id = payload["job_id"]

    st = _rpc("tools/call", {"name": "qa_status", "arguments": {"job_id": job_id}}, id_=4)
    assert st.status_code == 200
    st_body = json.loads(st.json()["result"]["content"][0]["text"])
    assert st_body["status"] == "queued"
    assert st_body["job_id"] == job_id

    rep = _rpc(
        "tools/call", {"name": "qa_get_report", "arguments": {"job_id": job_id}}, id_=5
    )
    assert rep.status_code == 200
    assert json.loads(rep.json()["result"]["content"][0]["text"])["job_id"] == job_id


def test_mcp_qa_preview_rejects_localhost() -> None:
    r = _rpc(
        "tools/call",
        {
            "name": "qa_preview",
            "arguments": {
                "url": "https://127.0.0.1/",
                "stories": [{"id": "home", "steps": [], "expect": "x"}],
            },
        },
        id_=6,
    )
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert result["isError"] is True
    assert "unsafe" in result["content"][0]["text"].lower()


def test_mcp_unknown_tool() -> None:
    r = _rpc("tools/call", {"name": "not_a_tool", "arguments": {}}, id_=7)
    assert r.status_code == 200
    err = r.json()["error"]
    assert err["code"] == -32602
    assert "not_a_tool" in err["message"]


def test_mcp_get_is_405() -> None:
    r = client.get("/mcp", headers={"Accept": "text/event-stream"})
    assert r.status_code == 405


def test_mcp_origin_evil_rejected() -> None:
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers={"Accept": ACCEPT, "Origin": "https://evil.example"},
    )
    assert r.status_code == 403


def test_mcp_origin_localhost_ok() -> None:
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers={"Accept": ACCEPT, "Origin": "http://127.0.0.1:8787"},
    )
    assert r.status_code == 200
    assert r.json()["result"] == {}


def test_mcp_sse_when_only_event_stream() -> None:
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 9, "method": "ping"},
        headers={"Accept": "text/event-stream"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert b"event: message" in r.content
    assert b'"result":{}' in r.content or b'"result": {}' in r.content


def test_mcp_qa_note_tool() -> None:
    from shipcheck.store import create_job, save_job

    job = create_job(
        {
            "url": "https://example.com/",
            "stories": [{"id": "home", "steps": [], "expect": "x"}],
            "viewport": "desktop",
            "price_usd": 6,
        }
    )
    job["status"] = "needs_review"
    save_job(job)
    r = _rpc(
        "tools/call",
        {
            "name": "qa_note",
            "arguments": {
                "job_id": job["job_id"],
                "human_note": "Confirmed broken checkout.",
                "verdict": "fail",
            },
        },
        id_=10,
    )
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["status"] == "needs_review"
    assert payload["human_verdict"] == "fail"
    assert payload["human_note"] == "Confirmed broken checkout."

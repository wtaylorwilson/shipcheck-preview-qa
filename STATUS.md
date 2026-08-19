# ShipCheck v0 status — Wed Aug 19, 2026 (ET)

## What works

- REST API: `GET /` (landing HTML), `POST /qa_preview`, `GET /qa_status/{job_id}`, `GET /qa_get_report/{job_id}`, `POST /qa_note/{job_id}`, `GET /health`.
- Streamable-HTTP MCP at `POST /mcp` (JSON-RPC 2.0, stateless JSON; SSE if `Accept` is only `text/event-stream`). Tools: `qa_preview`, `qa_status`, `qa_get_report`, `qa_note`. Same validation/SSRF as REST. Cursor config: `examples/mcp.json`.
- **Public URL:** `https://realtor-all-enclosed-altered.trycloudflare.com` (Cloudflare quick tunnel → `127.0.0.1:8787`). Confirmed `GET /health` 200 from this box. Written to `PUBLIC_URL.txt`.
- IP rate limit: 20 `qa_preview` jobs/UTC-day/IP (`CF-Connecting-IP` / `X-Forwarded-For`). Loopback unlimited. File: `ratelimit.json`.
- Disk queue + reports: `/workspace/shipcheck/queue/{job_id}.json`, `/workspace/shipcheck/reports/{job_id}.json`, screenshots under `/workspace/shipcheck/reports/{job_id}/`.
- Playwright heuristic pack (Chromium): HTTP status, console errors, failed network, empty body, suspicious visible text (`undefined` / `NaN` / error-class strings), expect-text, screenshot per story × viewport.
- All heuristics green → `pass`. Any fail → `needs_review` with `failures[]` listed; `human_note` stays null for a later pass.
- SSRF: https only; localhost / RFC1918 / link-local / CGNAT / metadata / file:// / credentials / redirect-to-private rejected on POST and again on every Playwright request.
- CLI: `python -m shipcheck serve|worker|run-job <id>`
- Billing hook (no-op): `shipcheck/billing.py` — `$6` desktop, `$10` both-viewports or 5–8 stories. Debit-on-success only, `job_id` idempotency. Keys accepted, never required, never charged.
- Tests: **78+ passed** (`tests/test_ssrf.py`, `tests/test_api.py` including landing + rate-limit, `tests/test_mcp.py`, live `tests/test_live.py` against https://example.com).
- Live Playwright: **passed**. example.com story `expect: Example Domain` → HTTP 200, screenshot written, status `pass`. Fail path also proven: missing expect → `needs_review`.

A server is currently listening at `http://127.0.0.1:8787` (inline worker on), serving REST, MCP, and `GET /`. Public via `cloudflared tunnel --url http://127.0.0.1:8787` (binary at `/workspace/shipcheck/cloudflared`, log `cloudflared.log`).

## How to start the server

```bash
cd /workspace/shipcheck
.venv/bin/python -m shipcheck serve --host 0.0.0.0 --port 8787
```

Health: `curl http://127.0.0.1:8787/health`

Public tunnel (no Cloudflare account; URL changes if this process dies):

```bash
/workspace/shipcheck/cloudflared tunnel --url http://127.0.0.1:8787 --no-autoupdate --logfile /workspace/shipcheck/cloudflared.log
```

Re-run tests: `.venv/bin/pytest tests -q`

## Leftover (not in v0)

- **Billing:** Polar prepaid credits + license key as `Authorization: Bearer`; call `debit()` after pass/needs_review only. No live Polar/Stripe.
- **Human note:** `POST /qa_note/{job_id}` and MCP `qa_note` exist; no Slack/Telegram ping on `needs_review`.
- **webhook_url:** accepted and SSRF-checked, not fired.
- **Listings:** PulseMCP / Glama / official registry / `llms.txt`.
- **auth_hint:** stored, not used to log in.
- **Named tunnel / custom domain:** quick tunnel only. Hostname is random (`*.trycloudflare.com`) and not permanent.

Do not add a dashboard, marketplace, GitHub App, or crypto rail.

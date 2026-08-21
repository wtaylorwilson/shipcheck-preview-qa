# ShipCheck v0 status — Fri Aug 21, 2026 (ET)

## What works

- REST API: `GET /` (landing HTML), `POST /qa_preview`, `GET /qa_status/{job_id}`, `GET /qa_get_report/{job_id}`, `POST /qa_note/{job_id}`, `GET /health`. HEAD supported on `/` and `/health`.
- Streamable-HTTP MCP at `POST /mcp` (JSON-RPC 2.0, stateless JSON; SSE if `Accept` is only `text/event-stream`). Tools: `qa_preview`, `qa_status`, `qa_get_report`, `qa_note`. Same validation/SSRF as REST. Cursor config: `examples/mcp.json`.
- **Listen port is 8788, not 8787.** `127.0.0.1:8787` is House Ring Timelapse (`python` pid 22446). Do not kill it. CLI `serve --port` default is now **8788** (flag still overrideable). Confirmed `GET http://127.0.0.1:8788/health` JSON ok: `{"ok":true,"service":"shipcheck","version":"0.1.0","mcp":true}` and `GET /` 200. Bound `127.0.0.1:8788` only.
- **Public URL:** none this morning. Previous `PUBLIC_URL.txt` hostname `consideration-complete-toronto-albums.trycloudflare.com` is NXDOMAIN. `bin-cloudflared.sh` adapted to 8788; Cloudflare quick tunnel returned **429 Too Many Requests (error 1015)** twice. Did not shop for another host. Local 8788 still counts. `PUBLIC_URL.txt` lists `http://127.0.0.1:8788` first.
- IP rate limit: 20 `qa_preview` jobs/UTC-day/IP (`CF-Connecting-IP` / `X-Forwarded-For`). Loopback unlimited. File: `ratelimit.json`.
- Disk queue + reports: `/workspace/shipcheck/queue/{job_id}.json`, `/workspace/shipcheck/reports/{job_id}.json`, screenshots under `/workspace/shipcheck/reports/{job_id}/`. Stuck job `sc_ee9a36723d94` (`https://example.com/`, status=running since 2026-08-20T14:01:44Z) marked **error** (stale worker died). No other queued/running jobs. Do not re-run the old queue.
- Playwright heuristic pack (Chromium): HTTP status, console errors, failed network, empty body, suspicious visible text (`undefined` / `NaN` / error-class strings), expect-text, screenshot per story × viewport.
- All heuristics green → `pass`. Any fail → `needs_review` with `failures[]` listed; `human_note` stays null for a later pass. Homepage expect-only is smoke (`needs_review`).
- SSRF: https only; localhost / RFC1918 / link-local / CGNAT / metadata / file:// / credentials / redirect-to-private rejected on POST and again on every Playwright request.
- CLI: `python -m shipcheck serve|worker|run-job <id>`
- Billing hook (no-op): `shipcheck/billing.py` — `$6` desktop, `$10` both-viewports or 5–8 stories. Debit-on-success only, `job_id` idempotency. Keys accepted, never required, never charged.
- Tests: **114 passed** (`pytest tests -q`) after recreating `.venv` with `pip install -e ".[dev]"` and `playwright install chromium` (`.venv` was gone again).
- Git: port default 8788 committed on `origin/main` (this ops pass).

A server is currently listening at `http://127.0.0.1:8788` (uvicorn, HEAD supported on `/` and `/health`), serving REST, MCP, and `GET /`. House Ring remains on 8787.

## How to start the server

```bash
cd /workspace/shipcheck
.venv/bin/python -m shipcheck serve --host 127.0.0.1 --port 8788
```

Health: `curl http://127.0.0.1:8788/health`

Public tunnel (no Cloudflare account; URL changes if this process dies; 429 this morning):

```bash
/workspace/shipcheck/bin-cloudflared.sh
```

Re-run tests: `.venv/bin/pytest tests -q`

## Leftover (not in v0)

- **Billing:** Polar prepaid credits + license key as `Authorization: Bearer`; call `debit()` after pass/needs_review only. No live Polar/Stripe.
- **Human note:** `POST /qa_note/{job_id}` and MCP `qa_note` exist; no Slack/Telegram ping on `needs_review`.
- **webhook_url:** accepted and SSRF-checked, not fired.
- **Listings:** PulseMCP / Glama / official registry / `llms.txt`.
- **auth_hint:** stored, not used to log in.
- **MCP registry publish:** not re-run. JWT expired yesterday (`401 Invalid or expired Registry JWT token`). Did not re-run interactive `mcp-publisher login github`.
- **Named tunnel / custom domain:** Cloudflare quick tunnel only, and it 429'd this morning. Hostname is random (`*.trycloudflare.com`) and not permanent when it does work.

Do not add a dashboard, marketplace, GitHub App, or crypto rail.

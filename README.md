# ShipCheck v0

Independent preview-URL QA for coding agents. An agent POSTs a public **https** preview URL plus acceptance stories. We run Playwright heuristics, screenshot each story, and return a pass/fail evidence pack. Failures stay `needs_review` until a human (or this agent looking at the page) adds a short note.

The same model that wrote the UI is a bad judge of the UI. That is the product.

Playwright MCP is free; this is not a hosted browser. It is an **independent check** with a human on fail. Screenshot APIs give pixels. ShipCheck answers "did story 3 actually work?"

## Run

```bash
cd /workspace/shipcheck
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/playwright install chromium
.venv/bin/python -m shipcheck serve --host 0.0.0.0 --port 8787
```

The venv already exists on this box. Default: the API process also drains the disk queue (inline worker). To split:

```bash
SHIPCHECK_INLINE_WORKER=0 .venv/bin/python -m shipcheck serve --port 8787
.venv/bin/python -m shipcheck worker
.venv/bin/python -m shipcheck run-job sc_xxxxxxxxxxxx
```

Health: `GET http://127.0.0.1:8787/health`

Public (Cloudflare quick tunnel, this box, Wed Aug 19 2026): **https://realtor-all-enclosed-altered.trycloudflare.com**
Same process serves `GET /` (landing), REST, and `POST /mcp`. URL also in `PUBLIC_URL.txt`. Quick tunnels die if `cloudflared` stops.

Jobs live at `/workspace/shipcheck/queue/{job_id}.json`. Reports and screenshots at `/workspace/shipcheck/reports/`.

## Example request / response

```bash
curl -sS -X POST https://realtor-all-enclosed-altered.trycloudflare.com/qa_preview \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "https://example.com/",
    "stories": [
      {"id": "home", "steps": ["open homepage"], "expect": "Example Domain"}
    ],
    "viewport": "desktop"
  }'
```

Response:

```json
{
  "job_id": "sc_ab12cd34ef56",
  "status": "queued",
  "price_usd": 6,
  "billed": false,
  "message": "queued. poll GET /qa_status/{job_id}; fetch GET /qa_get_report/{job_id} when status is pass or needs_review."
}
```

```bash
curl -sS https://realtor-all-enclosed-altered.trycloudflare.com/qa_status/sc_ab12cd34ef56
curl -sS https://realtor-all-enclosed-altered.trycloudflare.com/qa_get_report/sc_ab12cd34ef56
```

Terminal statuses: `pass` (all heuristics green, no human required) or `needs_review` (heuristic failures listed; a later pass adds `human_note` via `POST /qa_note/{job_id}` or MCP `qa_note`). `error` is our infrastructure (timeout, crash, unsafe URL) and is not billed.

Optional headers for later billing: `Authorization: Bearer <key>` or `X-Api-Key`. v0 accepts missing keys and does not debit.

Optional story steps (otherwise treated as notes): `click:css=.buy`, `click:text=Sign in`, `fill:#email|user@example.com`, `wait:1000`, `see:Order total`.

See `examples/sample_report.json` for the evidence-pack shape.

## Security

https only. Localhost, RFC1918, link-local, CGNAT, metadata IPs (`169.254.169.254`), `file://`, embedded credentials, and **redirect-to-private** are rejected. Every Playwright request is re-checked. 20s navigation timeout, 4 minute job cap. Details in `PRODUCT.md`.

SSRF tests (no live target required):

```bash
cd /workspace/shipcheck
python -m pytest tests/test_ssrf.py tests/test_api.py -q
```

## Cursor mcp.json

Streamable-HTTP MCP is served at `POST /mcp` (same process as REST). Tools: `qa_preview`, `qa_status`, `qa_get_report`, `qa_note`. Add this to `.cursor/mcp.json` or `~/.cursor/mcp.json` (omit `type`; Cursor treats a `url` as streamable HTTP):

```json
{
  "mcpServers": {
    "shipcheck": {
      "url": "https://realtor-all-enclosed-altered.trycloudflare.com/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY"
      }
    }
  }
}
```

v0 accepts a missing key and does not debit. Same file lives at `examples/mcp.json`. Server must be running (`python -m shipcheck serve --host 127.0.0.1 --port 8787`). Public URL is a Cloudflare quick tunnel in front of that process.

Landing page: `GET /` (HTML in `shipcheck/landing.html`). Public preview rate limit: **20 `qa_preview` jobs/day/IP** (loopback unlimited). `SHIPCHECK_PREVIEW_LIMIT_PER_IP` overrides; `0` disables.

## Pricing

Intent, not charged yet: **$6** desktop / **$10** both-viewports (or 5–8 stories) per run. Prepaid Polar credits later. Hook: `shipcheck/billing.py`.

## Next steps

1. Polar credit packs + license key as `Authorization: Bearer`; debit on success only.
2. Slack/Telegram ping when status is `needs_review`; human writes `human_note` (REST `POST /qa_note/{job_id}` and MCP `qa_note` already accept the note).
3. List on PulseMCP / Glama / official MCP registry (discovery, not a marketplace).
4. Public sample report + a 30-line `llms.txt`.

Do not add a dashboard, GitHub App, or crypto rail.

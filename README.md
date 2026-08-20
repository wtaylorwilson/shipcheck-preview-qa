# ShipCheck v0

Independent preview-URL QA for coding agents. An agent POSTs a public **https** preview URL plus a `goal`/`charter` (human-equivalent QA) or `click:`/`fill:`/`see:` stories. We walk the product in Playwright, screenshot, write a findings brief, and return a pass/fail evidence pack. Homepage expect-only is `needs_review` (`smoke only — no interaction`), not a pass.

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

Public (localhost.run, this box, Wed Aug 19 2026 ET): **https://91526eb1894540.lhr.life**
Same process serves `GET /` (landing), REST, and `POST /mcp`. Preferred URL in `PUBLIC_URL.txt` (backup Cloudflare quick tunnel, often blocked on consumer ISPs: `https://realtor-all-enclosed-altered.trycloudflare.com`). localhost.run dies if the ssh reverse tunnel stops; keep `ssh -R 80:localhost:8787 nokey@localhost.run` running.

Jobs live at `/workspace/shipcheck/queue/{job_id}.json`. Reports and screenshots at `/workspace/shipcheck/reports/`.

## Example request / response

Charter (preferred): a goal, not a click script. If `stories` is omitted, the explorer synthesizes the walk.

```bash
curl -sS -X POST https://91526eb1894540.lhr.life/qa_preview \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "https://example.com/",
    "goal": "Walk booking and check a Sat-Sat week uses the weekly rate",
    "viewport": "desktop"
  }'
```

Or pass explicit stories. If both `stories` and `goal` are set, we run the stories and the judge still uses the goal.

```bash
curl -sS -X POST https://91526eb1894540.lhr.life/qa_preview \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "https://example.com/",
    "stories": [
      {
        "id": "checkout",
        "steps": [
          "click:text=Book now",
          "fill:#email|guest@example.com",
          "see:Order total"
        ],
        "expect": "Order total"
      }
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
curl -sS https://91526eb1894540.lhr.life/qa_status/sc_ab12cd34ef56
curl -sS https://91526eb1894540.lhr.life/qa_get_report/sc_ab12cd34ef56
```

Terminal statuses: `pass` (heuristics green **and** stories executed `click:`/`fill:` — not homepage smoke, not an unfinished date/week charter) or `needs_review` (heuristic failures, smoke-only, **or** charter incomplete). Every finished job writes `human_note` (verdict, what was clicked, what failed, smoke checks) and `report.findings[]` `{severity, title, detail}` when steps or expects miss. A later human can still overwrite the note via `POST /qa_note/{job_id}` or MCP `qa_note`. `error` is our infrastructure (timeout, crash, unsafe URL) and is not billed.

Optional headers for later billing: `Authorization: Bearer <key>` or `X-Api-Key`. v0 accepts missing keys and does not debit.

Pass a `goal`/`charter` (max 500 chars) **or** story steps. Charter explorer v0: visible Book/Buy/Checkout/Cart/Setup/Rent/Continue/Add, then cart/setup/review if the goal needs dates/week/cart; Sat-Sat ISO dates when the goal asks for a week; no payment fill, no Send/Pay/Place order. An unfinished date/week/price charter is `needs_review` (`charter incomplete`), not pass. Story steps: `click:css=.buy`, `click:text=Sign in`, `fill:#email|user@example.com`, `wait:1000`, `see:Order total`. `click:` prefers a **visible** match (hidden mobile-nav CTAs lose to the hero/sticky button). Analytics/gtag/collect 429s are recorded but do not fail the job.

Homepage expect-only (`steps: ["open homepage"], expect: "Welcome"`) is **not a pass** — the report will say `smoke only — no interaction`.

See `examples/sample_report.json` for the evidence-pack shape.

## Security

https only. Localhost, RFC1918, link-local, CGNAT, metadata IPs (`169.254.169.254`), `file://`, embedded credentials, and **redirect-to-private** are rejected. Every Playwright request is re-checked. 20s navigation timeout, 4 minute job cap. Details in `PRODUCT.md`.

SSRF tests (no live target required):

```bash
cd /workspace/shipcheck
python -m pytest tests/test_ssrf.py tests/test_api.py tests/test_runner.py -q
```

## Cursor mcp.json

Streamable-HTTP MCP is served at `POST /mcp` (same process as REST). Tools: `qa_preview`, `qa_status`, `qa_get_report`, `qa_note`. Add this to `.cursor/mcp.json` or `~/.cursor/mcp.json` (omit `type`; Cursor treats a `url` as streamable HTTP):

```json
{
  "mcpServers": {
    "shipcheck": {
      "url": "https://91526eb1894540.lhr.life/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY"
      }
    }
  }
}
```

v0 accepts a missing key and does not debit. Same file lives at `examples/mcp.json`. Server must be running (`python -m shipcheck serve --host 127.0.0.1 --port 8787`). Public URL is a localhost.run ssh reverse tunnel in front of that process (Cloudflare quick tunnel kept as backup).

Landing page: `GET /` (HTML in `shipcheck/landing.html`). Public preview rate limit: **20 `qa_preview` jobs/day/IP** (loopback unlimited). `SHIPCHECK_PREVIEW_LIMIT_PER_IP` overrides; `0` disables.

## Pricing

Intent, not charged yet: **$6** desktop / **$10** both-viewports (or 5–8 stories) per run. Prepaid Polar credits later. Hook: `shipcheck/billing.py`.

## Next steps

1. Polar credit packs + license key as `Authorization: Bearer`; debit on success only.
2. Slack/Telegram ping when status is `needs_review`; human writes `human_note` (REST `POST /qa_note/{job_id}` and MCP `qa_note` already accept the note).
3. List on PulseMCP / Glama / official MCP registry (discovery, not a marketplace).
4. Public sample report + a 30-line `llms.txt`.

Do not add a dashboard, GitHub App, or crypto rail.

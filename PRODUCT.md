# ShipCheck

**One-liner:** An agent posts a public preview URL plus acceptance stories; we run Playwright heuristics (and a human writes a note on failures) and return a pass/fail evidence pack the coding agent cannot fake by grading itself.

## Who this is for

Operators of Cursor / Claude Code / Codex / cloud coding agents. The agent spends prepaid credits. The end customer never sees ShipCheck.

## Tools (REST and streamable-HTTP MCP)

Same tools on REST and at `POST /mcp`. Public: `https://realtor-all-enclosed-altered.trycloudflare.com/mcp`. Cursor: `examples/mcp.json`.

| Tool | HTTP | What it does |
|---|---|---|
| `qa_preview` | `POST /qa_preview` | Queue a run: `{url, stories[{id, steps[], expect}], viewport, auth_hint?}` |
| `qa_status` | `GET /qa_status/{job_id}` | queued / running / pass / needs_review / error |
| `qa_get_report` | `GET /qa_get_report/{job_id}` | Evidence pack: heuristics, screenshots, optional `human_note` |
| `qa_note` | `POST /qa_note/{job_id}` | Close `needs_review`: `{human_note, verdict: pass\|fail}` |

`viewport`: `desktop` | `mobile` | `both`. Default `desktop`.

## Pricing intent

Not billed in v0. The hook is `shipcheck/billing.py`.

| Run | Price |
|---|---|
| Desktop (or mobile), 1–4 stories | **$6** |
| Both viewports, **or** 5–8 stories | **$10** |

Prepaid credits later (Polar license key as API key, debit on successful completion only, `job_id` as idempotency key). Timeouts, SSRF rejects, and Playwright crashes are not billed.

Target: 10–20 runs/weekday. Capacity cap is honest: ~15 human-touched runs/day. Automated passes do not need a human.

## Security rules

- **https only.** `http://`, `file://`, `javascript:`, `data:` rejected.
- **No loopback:** `localhost`, `127.0.0.1`, `::1`, `*.localhost`.
- **No RFC1918 / link-local / CGNAT:** `10/8`, `172.16/12`, `192.168/16`, `169.254/16`, `100.64/10`.
- **No cloud metadata:** `169.254.169.254`, `metadata.google.internal`, IPv4-mapped IPv6 of the above.
- **No embedded credentials** in the URL.
- **Redirect-to-private is a fail.** Every Playwright request is re-checked (DNS + IP).
- Navigation timeout **20s**. Job cap **4 minutes**.
- Preview URL must still be live ~20 minutes (Vercel previews expire).
- `auth_hint` is for **public demo credentials only**. Do not send production secrets.
- ShipCheck does not log into your GitHub, does not scrape behind auth walls, and does not solve CAPTCHAs.

## What v0 does not do

No marketplace, dashboard SPA, auth platform, crypto payments, visual-regression AI, or GitHub App. Independent check + a human note on fail is the product.

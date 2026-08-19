# ShipCheck directory listings

Checked and submitted **Wed Aug 19, 2026 ~9:58 AM ET** (13:58 UTC) from this box.

**Product (honest copy):** Independent preview-URL QA for coding agents. An agent posts a public https preview URL plus acceptance stories; ShipCheck runs Playwright heuristics and returns a pass/fail evidence pack. Localhost / private IPs rejected. **v0: no billing yet** (intent $6 desktop / $10 both-viewports). Rate limit 20 jobs/IP/day. Public hostname is a Cloudflare **quick tunnel and may change**.

**Live now:** https://realtor-all-enclosed-altered.trycloudflare.com
**MCP:** `POST https://realtor-all-enclosed-altered.trycloudflare.com/mcp`
**Tools:** `qa_preview`, `qa_status`, `qa_get_report`, `qa_note`

`gh` on this box: **not logged in**. No GitHub repo was created. No paid signup. No new OAuth login was started.

Name collision: the official registry and PulseMCP already list a **different** product, TateLyman / shipcheck-mcp (launch-risk scans for JS/TS repos) at https://www.pulsemcp.com/servers/tatelyman-shipcheck. That is not this ShipCheck. Use a distinct display name if a form would collide (e.g. "ShipCheck preview QA").

---

## Went through (attempted)

| Directory | Submitted | Live listing URL | Blocker / notes |
|---|---|---|---|
| MCP Server Hub (mcpserverhub.net) | Yes (free public form) | Not live yet. Expected: https://mcpserverhub.net/server/shipcheck (404 now) | Accepted success 9:58 AM ET. Review queue. |
| PulseMCP | No | - | Form paused (still says until mid-August). https://www.pulsemcp.com/submit. Publish official registry first. Other product already at /servers/tatelyman-shipcheck. |
| Smithery | No | - | Needs Smithery account. Docs smithery.ai/new redirects to /servers/new (404). CLI and API return 401. Did not start login. |
| Glama | No | - | Servers need GitHub repo + OAuth. Connectors: add on https://glama.ai/mcp/connectors needs a Glama account. |
| mcp.so | No | - | Web form is 39 USD paid only. Skipped. Free path is GitHub issue at github.com/chatmcp/mcp-directory/issues (needs GitHub login). |
| Official MCP Registry | No | - | Publish needs Authorization. Namespace io.github.USER via mcp-publisher login, or DNS TXT. gh not authenticated. Draft server.json in this folder. |
| cursor.directory | No | - | plugins/new needs GitHub or Google plus a public repo with .mcp.json. No repo. |
| mcpfind.org | No | - | Submit form needs GitHub repo plus published package plus GitHub PR. |
| mcpservers.org | No | - | Free form at mcpservers.org/submit. Skip Premium. Requires contact email. Did not invent one. |
| awesome-mcp.tools | Tried | - | Public submit API requires a GitHub owner/repo URL. Returned 400. |
| MCPCentral | No | - | Needs mcp-publisher GitHub login against registry.mcpcentral.io, or site sign-in. |

---

## What Taylor can finish

Shared copy (honest; do not claim customers, SLA, or live billing):

> ShipCheck (v0) -- Independent preview-URL QA for coding agents. Agent posts a public https preview + acceptance stories; we run Playwright heuristics and return a pass/fail evidence pack. Localhost/private IPs rejected. No billing yet. Public URL is a Cloudflare quick tunnel and may change.
>
> MCP: https://realtor-all-enclosed-altered.trycloudflare.com/mcp
> Landing: https://realtor-all-enclosed-altered.trycloudflare.com/
> Tools: qa_preview, qa_status, qa_get_report, qa_note

### 1. mcpservers.org (free, needs your email)

1. Open https://mcpservers.org/submit
2. Server Name: ShipCheck
3. Short Description: the one-liner above
4. Link: https://realtor-all-enclosed-altered.trycloudflare.com
5. Category: Development
6. Contact Email: yours
7. Leave Premium unchecked. Submit.

### 2. PulseMCP

- Recheck https://www.pulsemcp.com/submit -- if the form is back, paste the landing URL.
- Better: publish to the official registry first. PulseMCP says they ingest that automatically.
- Optional expedite after registry publish: email hello@pulsemcp.com with server name + namespace. This is not TateLyman shipcheck-mcp.

### 3. Official MCP Registry (unblocks PulseMCP / Glama ingest)

On a machine where you can log in to GitHub:

    mcp-publisher login github
    mcp-publisher publish

Edit server.json name to io.github.YOURUSER/shipcheck before publish. Do not reuse io.github.TateLyman/shipcheck-mcp. Tunnel URL goes stale if cloudflared restarts -- bump version and republish.

### 4. Smithery (self-hosted URL)

1. Create a free account at https://smithery.ai
2. Try https://smithery.ai/new -- if still 404, use in-app publish or: npx smithery auth login && npx smithery mcp publish URL -n YOURORG/shipcheck
3. URL: https://realtor-all-enclosed-altered.trycloudflare.com/mcp
4. v0 accepts a missing key and does not debit.

### 5. Glama connector (URL, no repo)

1. Sign in at https://glama.ai
2. https://glama.ai/mcp/connectors then Add MCP Server then Connector
3. Name: ShipCheck. URL: https://realtor-all-enclosed-altered.trycloudflare.com/mcp (streamable-http)
4. No test credentials (v0 is open). Only healthy connectors are indexed.
5. Claiming later needs .well-known/glama.json on a domain you control. A trycloudflare host is a poor claim target.
6. Open-source server listing needs a public GitHub repo (not created).

### 6. mcp.so (free GitHub issue -- do not pay)

1. Sign in to GitHub.
2. Open https://github.com/chatmcp/mcp-directory/issues/new (or mcp.so Submit then the GitHub path, not Pay and submit).
3. Title: [Submit] ShipCheck -- independent preview-URL QA for coding agents
4. Body: one-liner + MCP URL + tools + v0, no billing, tunnel hostname may change.

### 7. cursor.directory

Needs a public GitHub repo first (this box did not create one). Then add a repo-root .mcp.json (same as examples/mcp.json). Go to https://cursor.directory/plugins/new, sign in, paste the repo URL, Submit.

---

## Suggested official server.json

Written to /workspace/shipcheck/server.json. Replace YOUR_GITHUB_USER. Official description max length is 100 characters.

Replace the name field with your GitHub namespace before publish. Do not use io.github.TateLyman or a title that collides with shipcheck-mcp (repo risk scans).

---

## What we did not do

- Did not create a GitHub repo or start gh auth login.
- Did not pay mcp.so or mcpservers.org premium.
- Did not post Show HN or Reddit (draft only: LAUNCH.md).
- Did not invent a marketplace or claim paying customers, SLA, or live billing.


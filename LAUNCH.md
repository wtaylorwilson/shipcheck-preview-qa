# Launch drafts -- do not post from this box

These are copy-only. They were not posted to HN, Reddit, Twitter, or anywhere that needs Taylor identity.

Public URL (Wed Aug 19, 2026): https://realtor-all-enclosed-altered.trycloudflare.com
MCP: https://realtor-all-enclosed-altered.trycloudflare.com/mcp

The hostname is a Cloudflare quick tunnel. If it dies, update before posting.

---

## Show HN

Title: Show HN: ShipCheck -- independent preview-URL QA for coding agents

Body:

The same model that wrote the UI is a bad judge of the UI.

ShipCheck is a small hosted check for coding agents (Cursor, Claude Code, Codex, cloud agents). The agent POSTs a public https preview URL plus a few acceptance stories. We run Playwright heuristics, screenshot each story, and return a pass/fail evidence pack. Failures stay needs_review until a human (or the agent looking at the page) writes a short note.

It is not a hosted browser and not Playwright MCP. Localhost, private IPs, metadata IPs, and redirect-to-private are rejected.

v0 is live on a Cloudflare quick tunnel (hostname will change if the process restarts). No billing yet. Intent later: 6 USD desktop / 10 USD both-viewports. Rate limit 20 jobs/IP/day.

MCP tools: qa_preview, qa_status, qa_get_report, qa_note
Endpoint: POST /mcp on the public URL
Landing: GET /

Distinct from the existing registry entry by TateLyman.
Happy to hear why this is the wrong shape.

## r/mcp

Title: ShipCheck v0 -- preview-URL QA MCP (Playwright heuristics, no self-grade)

Built a remote MCP for operators of coding agents: the agent hands us a public https preview plus acceptance stories; we run Playwright heuristics and return a pass/fail evidence pack. Failures need a human note (qa_note). We refuse localhost and private IPs.

Streamable-HTTP at /mcp. Tools: qa_preview, qa_status, qa_get_report, qa_note.

v0: no API keys required, no charges. Tunnel URL may change. Intent pricing only (6 / 10 USD). 20 jobs per IP per day.

Not a marketplace. Distinct from the TateLyman registry entry.

Put the live URL in a follow-up comment if the tunnel is still up when you post.

## Posting checklist (Taylor)

1. Confirm GET /health still 200 on the public URL.
2. If the tunnel hostname changed, update PUBLIC_URL.txt and this draft before posting.
3. Show HN: https://news.ycombinator.com/submit -- your HN account.
4. Reddit: https://www.reddit.com/r/mcp/submit -- your Reddit account.
5. Do not claim paying customers, SLA, or that billing is live.

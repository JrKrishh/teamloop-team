# Deploy a self-hosted hub

The hosted hub (teamloop.vercel.app, `cloud/`) is deployed as part of a release: [release.md](release.md). This page is
for running your own hub (`hub/`): the connector and a web board with a room token, without accounts. The desktop app
and the phone need the hosted hub.

Every model call goes to Nebius Token Factory, so the hub itself can run on a free host.

## Where
A self-hosted hub needs a long-running process and a disk (SQLite), so:
- **Your own machine:** `teamloop hub` (data in `~/.teamloop/hub/`). For teammates elsewhere, `cloudflared tunnel --url
  http://localhost:8799`, then `teamloop hub --public-url <that URL>`.
- **Any Docker host** with the repo's `Dockerfile`, for example Render's free web service (it sleeps after 15 minutes
  idle and takes about a minute to wake). Hugging Face's free Docker Spaces need a PRO subscription since 13 Oct 2026.

## Settings
| Setting | What |
|---|---|
| `NEBIUS_API_KEY` | Agent S on NVIDIA Nemotron (Token Factory). Without it, Ask and the digest answer "unavailable" |
| `HUB_SECRET` | a long random string for cookie signing |
| `CCBRIDGE_ROOMS`, `CCBRIDGE_OPEN_ROOMS=0` | `teamloop:<room token>` for a team's room. Members and their connectors use this token |
| `HUB_LEAD_KEYS` | `teamloop:<lead key>`: board sign-in as lead (invite, remove members, settings). Without it, the room-token holder is lead |
| `HUB_DEMO_ROOM` | optional: a public read-only sample room (`demo`, from `hub/hub/demo/demo.json`) |
| `GITHUB_WEBHOOK_SECRET`, `HUB_GITHUB_REPOS` | PR, review and CI state on the cards: see [github-setup.md](github-setup.md) (the hosted hub doesn't have this) |
| `HUB_NOTIFY_WEBHOOK` | optional: a Discord or Slack webhook for blocker pings |
| `HUB_DEMO_ASKS_PER_10MIN` | the demo room's question limit (default 20), to protect the credits |

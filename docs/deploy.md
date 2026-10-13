# Deploy the hub (PLAN.md §6.5, decisions D8 and D8b)

**Live demo: https://teamloop.vercel.app** (public demo room, read-only, live board).

Every model call goes to Nebius Token Factory, which counts as "runs on Nebius" under the rules, so the hub can run on a free host.

## Why not Hugging Face Spaces
On 13 Oct 2026, HF refused to create a Docker Space: *"hosting Gradio and Docker Spaces on free cpu-basic requires a PRO subscription"* (HTTP 402). Only static Spaces are free now. The `Dockerfile` still works for any Docker host.

## Vercel (the demo, free Hobby plan)
The repo root has `api/index.py` (the hub as one Python function), `vercel.json` (send every path to it) and `.vercelignore` (upload only the hub and Agent S).

```bash
vercel link --yes --project teamloop
vercel env add HUB_SECRET production        # any long random string (cookie signing)
vercel env add NEBIUS_API_KEY production    # Agent S answers and digest; the board works without it
vercel deploy --prod --yes
```

**Limits on Vercel:**
- **The SQLite file lives in `/tmp`,** which is per instance and temporary. The demo room re-seeds itself on every cold start, but real-team data would not survive. Real teams need the persistent store first (below).
- **The live stream reconnects about once a minute** (function max duration 60 s). The board reconnects by itself and falls back to polling.
- **The Agent S worker only runs while an instance is warm.** That's fine for the demo: its snapshots ship pre-built in `hub/hub/demo/demo.json`. Re-run `scripts/build_demo.py` with `AGENT_S_PROVIDER=nebius` to refresh them.

## A host for real teams
Real teams need a long-running process and a disk, so pick one of these:
- **Render free web service:** Docker, no card, 512 MB. It sleeps after 15 minutes idle and takes about a minute to wake. Its free Postgres expires after 30 days. Use the `Dockerfile` as-is.
- **Vercel + a hosted Postgres** (for example Supabase free): means swapping SQLite for Postgres in `hub/`. Decide by Oct 24 (PLAN.md §6.5).

## Settings (all hosts)
| Setting | What |
|---|---|
| `NEBIUS_API_KEY` | Agent S on NVIDIA Nemotron (Token Factory). Without it, Ask and the digest answer "unavailable" |
| `HUB_SECRET` | a long random string for cookie signing |
| `HUB_DEMO_ROOM` | `demo`: the public read-only sample room (set by `api/index.py` and the `Dockerfile`) |
| `CCBRIDGE_ROOMS`, `CCBRIDGE_OPEN_ROOMS=0` | `teamloop:<room token>` for a real team's room. Members and their connectors use this token |
| `HUB_LEAD_KEYS` | `teamloop:<lead key>`: board sign-in as lead (invite, remove members, settings). Without it, the room-token holder is lead |
| `GITHUB_WEBHOOK_SECRET`, `HUB_GITHUB_REPOS` | see [github-setup.md](github-setup.md) |
| `HUB_NOTIFY_WEBHOOK` | optional: a Discord or Slack webhook for blocker pings |
| `HUB_DEMO_ASKS_PER_10MIN` | public demo question limit (default 20), to protect the credits |

# Deploy the hub (PLAN.md §6.5, decision D8)

The hub and board ship as one Docker image (`Dockerfile` at the repo root). Every model call goes to Nebius Token Factory, which counts as "runs on Nebius" under the rules, so the container itself can run on a free host.

## Hugging Face Spaces (free, recommended)
1. Create a Space: **SDK = Docker**, visibility public, hardware *CPU basic* (free).
2. Push this repo to it. The Space README needs this front matter:
   ```yaml
   ---
   title: TeamLoop
   sdk: docker
   app_port: 7860
   ---
   ```
3. Add these **Secrets** under Settings → Variables and secrets:

   | Secret | Value |
   |---|---|
   | `NEBIUS_API_KEY` | Agent S on NVIDIA Nemotron |
   | `HUB_SECRET` | a long random string for cookie signing |
   | `CCBRIDGE_ROOMS` | `teamloop:<room token>` for your real team's room |
   | `CCBRIDGE_OPEN_ROOMS` | `0` |
   | `GITHUB_WEBHOOK_SECRET` | see [github-setup.md](github-setup.md) |
   | `HUB_GITHUB_REPOS` | see [github-setup.md](github-setup.md) |

4. The image sets `HUB_DEMO_ROOM=demo`. Anyone opening the Space URL sees the public sample team, read-only. Teammates sign in to their own room with its token.

## Keep it awake until judging ends (15 Dec)
Free Spaces sleep after 48 h without traffic. A daily GitHub Actions job that runs `curl -fsS https://<space>.hf.space/healthz` keeps it up.

## Limits to know
- **The SQLite file lives in `/tmp`**, so a restart wipes real-team data. The demo room re-seeds itself at boot. Before outside teams rely on the hub, move real data to a persistent store (Supabase free, decided by Oct 24, PLAN.md §6.5).
- **Public demo questions are limited** to `HUB_DEMO_ASKS_PER_10MIN` (default 20) to protect the credits.
- **The demo snapshots** come from `scripts/build_demo.py`, which runs the real Agent S. Re-run it with `AGENT_S_PROVIDER=nebius` once credits are live, so the demo shows Nemotron output.

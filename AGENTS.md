# Working in this repo (for coding agents and humans)

The product is **Super Agents**: a Windows desktop app, a phone app, and the hosted hub they talk to. The README's
"Where things live" maps the folders; `docs/` has the details. `PLAN.md` is the plan of 13 Oct: its reasoning still
holds, its scope and schedule don't.

## Layout
- `app/`: the desktop app (`SuperAgents.exe`). `server.py` is the local API the UI calls, `runtime/` the agent loop and
  its tools, `ui/` the page, `remote.py` the phone link, `superteam.py` the runner for teammates' prompts. Docs: `docs/app.md`.
- `connector/`: `teamloop` on each laptop (`teamloop.exe`): hook shim, spool, redaction, git trailer, MCP server,
  summarizer, sender, CLI.
- `cloud/`: the hosted hub on Vercel and Supabase, and the website (`cloud/cloud/site`). Docs: `docs/cloud.md`;
  database changes go in `cloud/cloud/migrations.sql` and `schema.sql` together.
- `hub/`: the self-hosted hub, plus what both hubs share (`cards.py`, `usage.py`, `team.py`'s event checks, `safety.py`).
  `relay.py` and `safety.py` are ccbridge c1f3385 (Sourabh, MIT) with one marked change. Event API: `docs/hub-api.md`.
- `agent_s/`: Agent S, honest cited progress, answers and the digest (Nemotron on Token Factory; Ollama in development).
  Eval: `python scripts/eval_agent_s.py` over `agent_s/golden/`.
- `android/`: the phone app (Kotlin, Compose). `packaging/`: the Windows build and installer.

## Commands
- Tests: `python -m pytest -q` in `connector/`, `app/`, `hub/`, `agent_s/` and `cloud/` (install: `uv pip install -e agent_s
  -e connector -e "hub[dev]" -e "cloud[dev]" -e "app[dev]"`), and `./gradlew testDebugUnitTest` in `android/`.
- Before every commit: the tests pass. In development and tests, never connect a repo with the real `claude` or `codex`
  CLIs on PATH: registering the MCP server writes your user-level config.
- Releasing: `docs/release.md` (one version for every part; `app/tests/test_versions.py` checks it).

## Rules that protect users (tests enforce them)
1. **The hook never breaks a session.** No network, no stdout output, always exit 0; errors go to `~/.teamloop/hook.log`.
   No subprocess, except one detached `teamloop send` at session end (the MCP-hosted sender exits with the session).
2. **Free text from hooks lives only in `local`.** `facts` hold structured values only. MCP self-reports go in `report`:
   the agent writes them for the team on purpose, and they're redacted and capped at 5 items of 160 chars. Events bound
   for the hub go through `spool.public()`; `local` text reaches the hub only through `summarize.py` (`/v1/summarize`,
   which keeps nothing), and the event carries the summary, never the text.
3. **Redact before writing anything**, even to the local spool.
4. **Agent transcripts are read only on the laptop:** the connector takes only numbers from them (token counts,
   `usage.py`), and the app's recall index over them stays local (what a search finds goes to the model like any tool
   result). Vendors say the format is internal, so a reader must survive any shape.
5. **No machine paths** in events: repo-relative paths or the bare file name only.
6. New tool support starts with **real captured payloads** in `connector/tests/fixtures/hooks/<tool>/`, never with field
   names guessed from docs.
7. **Child processes get `stdin=DEVNULL`.** Inside the MCP server, stdin is the protocol pipe, and an inheriting child
   stalls on Windows.
8. **The hubs check what comes in:** an event's shape (`hub.team.bad_shape`), and teammates' text that other people's agents
   read is cleaned (`hub.safety.sanitize`).

## Commits
Branch `T-<id>-slug`; run `teamloop task T-<id>` so the commit hook adds `TeamLoop-Task: T-<id>`. Don't add co-author or
attribution lines.

## Progress reporting (MCP server: `teamloop mcp`, registered by `teamloop init`)
Call `task_start` when you begin a task, `report_progress` after each meaningful step, `mark_blocked` when you can't
proceed, and `get_team_status` before starting work that might overlap a teammate's.

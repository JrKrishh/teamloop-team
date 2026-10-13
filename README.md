# TeamLoop Team

Live progress from every teammate's AI coding session (Claude Code, Codex, Cursor) on one board, without anyone typing a status update.

> **Status: building.** Started 13 Oct 2026 for the Nebius × NVIDIA Global AI Hackathon. **Live demo: https://teamloop.vercel.app**. See [PLAN.md](PLAN.md).

## How it works
1. Each developer installs the `teamloop` connector. Their coding tool's hooks call it after every turn and tool call.
2. The connector writes each event to a local spool. Secrets are hidden first, and file paths are made repo-relative.
3. Free text, like the agent's last message, stays on the laptop. It is only used to write a short summary.
4. Summaries and structured facts (files changed, tests passed or failed, commits) go to the team hub. There, Agent S, running on NVIDIA Nemotron via Nebius Token Factory, turns them into per-task progress.

**Never shared:** prompts, tool output, file contents, diffs, keystrokes, screenshots. No rankings, no time tracking.

## Install on Windows (teamloop.exe, no Python needed)
1. Unzip `teamloop-0.1.1-windows-x64.zip` (CI's `exe` job builds it; locally: `pyinstaller packaging/teamloop.spec`).
2. Run `powershell -ExecutionPolicy Bypass -File install.ps1` in that folder. It copies to `%LOCALAPPDATA%\TeamLoop` and adds it to your PATH.
3. **Teammate:** `teamloop login <invite>`, then `teamloop init` in your repo and `teamloop task T-1 "..."`.
4. **Lead (self-hosted):** `teamloop hub`. It creates your room, a room token and a lead key, keeps data in `~/.teamloop/hub/`, opens the board, and prints the teammate invite. For teammates elsewhere, run `cloudflared tunnel --url http://localhost:8799`, then `teamloop hub --public-url <that URL>`.

The same exe is the hook handler and the MCP server, so `init` points Claude Code and Codex at it. **Hooks cost about 0.4 s per tool call** with the exe (Python startup), against about 0.17 s when installed with pip.

## Connector (works today)
```bash
cd connector && uv venv && uv pip install -e ".[dev]"
cd /path/to/your/repo
teamloop init                     # Claude Code (+ Codex if installed): hooks, MCP server, commit-trailer hook
teamloop task T-14 "Add SSE"      # what this repo is working on
teamloop doctor                   # every check, with the command that fixes it
teamloop pause                    # record nothing until `teamloop resume`
```
`init` writes hooks to `.claude/settings.local.json` (personal, kept out of git), so teammates without TeamLoop are never affected. Use `--scope user` to cover every repo, and `--dry-run` to preview.

Codex asks you once to trust the repo's hooks (`codex`, then `/hooks`).

Your agent gets four MCP tools: `task_start`, `report_progress`, `mark_blocked` and `get_team_status` (what teammates are doing). Commits get a `TeamLoop-Task:` trailer, even with `--no-verify`.

## Hub and board (works today)
```bash
uv pip install -e agent_s -e connector -e "hub[dev]"
CCBRIDGE_ROOMS="teamloop:<room token>" CCBRIDGE_OPEN_ROOMS=0 HUB_SECURE_COOKIE=0   uvicorn hub.app:app_from_env --factory --port 8799        # HUB_SECURE_COOKIE=0 only for plain http on localhost
teamloop invite --url http://<hub>:8799 --room teamloop --token <room token>   # share this with the team
teamloop login <invite> --name yang                                            # each teammate, once
```
Open `http://<hub>:8799/`, sign in with the room and token, and watch tasks fill in.

**Agent S's model:** set `NEBIUS_API_KEY` for NVIDIA Nemotron on Token Factory. Otherwise it uses a local Ollama model (`AGENT_S_PROVIDER=ollama`).

**GitHub:** see [docs/github-setup.md](docs/github-setup.md).

## Tests
```bash
cd connector && .venv/Scripts/python -m pytest -q      # or .venv/bin/python on macOS/Linux
```

## Credits
- [ccbridge](https://github.com/sourabhnirvani/ccbridge) (MIT, by Sourabh, @sourabhnirvani): relay, rooms, invites and prompt-injection safety. The hub builds on it.
- TeamLoop neatHack (MIT): Agent S, the Hoodie design and colours, the mascot art (`hub/hub/static/mascot`), and secret redaction.

MIT licensed.

# TeamLoop Team

Live progress from every teammate's AI coding session (Claude Code, Codex, Cursor) on one board, without anyone typing a status update.

> **Status: building.** Started 13 Oct 2026 for the Nebius × NVIDIA Global AI Hackathon. See [PLAN.md](PLAN.md).

## How it works
1. Each developer installs the `teamloop` connector. Their coding tool's hooks call it after every turn and tool call.
2. The connector writes each event to a local spool. Secrets are hidden first, and file paths are made repo-relative.
3. Free text, like the agent's last message, stays on the laptop. It is only used to write a short summary.
4. Summaries and structured facts (files changed, tests passed or failed, commits) go to the team hub. There, Agent S, running on NVIDIA Nemotron via Nebius Token Factory, turns them into per-task progress.

**Never shared:** prompts, tool output, file contents, diffs, keystrokes, screenshots. No rankings, no time tracking.

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

Your agent gets three MCP tools: `task_start`, `report_progress` and `mark_blocked`. Commits get a `TeamLoop-Task:` trailer, even with `--no-verify`.

## Tests
```bash
cd connector && .venv/Scripts/python -m pytest -q      # or .venv/bin/python on macOS/Linux
```

## Credits
- [ccbridge](https://github.com/sourabhnirvani/ccbridge) (MIT, by Sourabh, @sourabhnirvani): relay, rooms, invites and prompt-injection safety. The hub builds on it.
- TeamLoop neatHack (MIT): Agent S, the Hoodie design, mascots and secret redaction.

MIT licensed.

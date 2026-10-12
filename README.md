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
cd connector
uv venv && uv pip install -e ".[dev]"
teamloop git-hook install         # adds "TeamLoop-Task: T-14" trailers to your commits
teamloop task T-14 "Add SSE"      # what this repo is working on
teamloop status
teamloop pause                    # record nothing until `teamloop resume`
```
Claude Code hook (`.claude/settings.json`): run `teamloop hook claude_code` on `SessionStart`, `PostToolUse`, `PostToolUseFailure`, `Notification`, `Stop`, `SubagentStop` and `SessionEnd`. `teamloop init` will write this for you; it isn't built yet.

## Tests
```bash
cd connector && .venv/Scripts/python -m pytest -q      # or .venv/bin/python on macOS/Linux
```

## Credits
- [ccbridge](https://github.com/sourabhnirvani/ccbridge) (MIT, by Sourabh, @sourabhnirvani): relay, rooms, invites and prompt-injection safety. The hub builds on it.
- TeamLoop neatHack (MIT): Agent S, the Hoodie design, mascots and secret redaction.

MIT licensed.

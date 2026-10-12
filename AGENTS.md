# Working in this repo (for coding agents and humans)

Read `PLAN.md` first. §5 is the scope contract, §15 is the schedule and §26 is the decision log. Don't add features outside §5.1 until the MVP is green.

## Layout
- `connector/`: the `teamloop` CLI on each developer's laptop: hook shim, spool, redaction, git trailer, MCP server, summarizer, sender. Owned by Yang.
- `hub/`: team server. `hub/relay.py` and `hub/safety.py` are ccbridge c1f3385 (Sourabh, MIT) with one marked change; `hub/team.py` adds events, Agent S progress, board and Q&A. Owned by Sourabh (started by Yang's agent on 13 Oct at Yang's call). Contract: `docs/hub-api.md`. Run: `uvicorn hub.app:app_from_env --factory --port 8787`.
- `agent_s/`: Agent S, honest cited progress from events (Nemotron on Token Factory; Ollama in dev). The hub imports it. Owned by Yang. Eval: `python scripts/eval_agent_s.py` over `agent_s/golden/`.
- `board/`: web board in the Hoodie design. Not started.
- `docs/research/`: sources behind decisions. `docs/decisions/`: numbered decision records.

## Commands
- Tests: `cd connector && .venv/Scripts/python -m pytest -q`, and the same in `agent_s/` and `hub/` (install: `uv pip install -e agent_s -e connector -e "hub[dev]"`)
- Before every commit: the tests pass.

## Rules that protect users (tests enforce them)
1. **The hook never breaks a session.** No network, no subprocess, no stdout output, always exit 0. Errors go to `~/.teamloop/hook.log`.
2. **Free text from hooks lives only in `local`.** `facts` hold structured values only. MCP self-reports go in `report`: the agent writes them for the team on purpose, and they're redacted and capped at 5 items of 160 chars. Anything bound for the hub goes through `spool.public()`.
3. **Redact before writing anything**, even to the local spool.
4. **Never parse agent transcripts** (`transcript_path`). Vendors say the format is internal.
5. **No machine paths** in events: repo-relative paths or the bare file name only.
6. New tool support starts with **real captured payloads** in `connector/tests/fixtures/hooks/<tool>/`, never with field names guessed from docs.
7. **Child processes get `stdin=DEVNULL`.** Inside the MCP server, stdin is the protocol pipe, and an inheriting child stalls on Windows.

## Commits
Branch `T-<id>-slug`; run `teamloop task T-<id>` so the commit hook adds `TeamLoop-Task: T-<id>`. Don't add co-author or attribution lines.

## Progress reporting (MCP server: `teamloop mcp`, registered by `teamloop init`)
Call `task_start` when you begin a task, `report_progress` after each meaningful step, and `mark_blocked` when you can't proceed.

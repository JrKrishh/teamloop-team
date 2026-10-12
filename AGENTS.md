# Working in this repo (for coding agents and humans)

Read `PLAN.md` first. §5 is the scope contract, §15 is the schedule and §26 is the decision log. Don't add features outside §5.1 until the MVP is green.

## Layout
- `connector/`: the `teamloop` CLI that runs on each developer's laptop: hook shim, spool, redaction, git trailer and, later, the summarizer and MCP server. Owned by Yang.
- `hub/`: team server, built from the ccbridge relay. Owned by Sourabh. Not started.
- `board/`: web board in the Hoodie design. Not started.
- `docs/research/`: sources behind decisions. `docs/decisions/`: numbered decision records.

## Commands
- Tests: `cd connector && .venv/Scripts/python -m pytest -q`
- Before every commit: the tests pass.

## Rules that protect users (tests enforce them)
1. **The hook never breaks a session.** No network, no subprocess, no stdout output, always exit 0. Errors go to `~/.teamloop/hook.log`.
2. **Free text lives only in `local`.** `facts` hold structured values only. Anything bound for the hub goes through `spool.public()`.
3. **Redact before writing anything**, even to the local spool.
4. **Never parse agent transcripts** (`transcript_path`). Vendors say the format is internal.
5. **No machine paths** in events: repo-relative paths or the bare file name only.
6. New tool support starts with **real captured payloads** in `connector/tests/fixtures/hooks/<tool>/`, never with field names guessed from docs.

## Commits
Branch `T-<id>-slug`; run `teamloop task T-<id>` so the commit hook adds `TeamLoop-Task: T-<id>`. Don't add co-author or attribution lines.

## Progress reporting (once the MCP server exists)
Call `task_start` when you begin a task, `report_progress` after each meaningful step, and `mark_blocked` when you can't proceed.

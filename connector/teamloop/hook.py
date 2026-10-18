"""`teamloop hook <tool>`: hook JSON on stdin -> normalize -> redact -> spool.

Rules: no network, no subprocess (except one detached `send` at session end), print nothing (Claude Code adds SessionStart stdout to the model's context)
except one context block when teammates' notes are waiting for this session (read from the local inbox, see messages.py),
and always exit 0 so a TeamLoop bug can never block the developer's session.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback

from teamloop import messages, redact, repo, spool, usage
from teamloop.normalize import NORMALIZERS

# Claude Code adds these hooks' `additionalContext` to what the model reads next (checked in its own schema, 18 Oct).
# Not Stop: context there could set a finished agent going again.
CONTEXT_EVENTS = {"SessionStart", "PostToolUse", "PostToolUseFailure"}


def handle(tool: str, raw: bytes) -> dict | None:
    if spool.paused():
        return None
    payload = json.loads(raw.decode("utf-8") or "{}")
    found = repo.find(payload.get("cwd") or os.getcwd())
    event = NORMALIZERS[tool](payload, found.root if found else None)
    if event is None:
        return None
    add_usage(tool, payload, event)
    event["repo"] = found.root.name if found else None
    event["branch"] = repo.branch(found) if found else None
    event["task"] = repo.task(found)
    event = redact.redact_obj(event)
    spool.append(event)
    if event["kind"] == "session_end":
        flush_detached()
    return event


def add_usage(tool: str, payload: dict, event: dict) -> None:
    """The turn's token counts from the agent's transcript (numbers only). A failure here never costs the event."""
    try:
        if event["kind"] == "session_start" and payload.get("transcript_path"):
            usage.started(tool, payload["transcript_path"])
        elif event["kind"] == "turn_end":
            counts = usage.for_turn(tool, payload)
            if counts:
                event["facts"]["usage"] = counts
    except Exception:  # noqa: BLE001 - logged like any hook error
        log(tool)


def log(tool: str) -> None:
    try:
        path = spool.home() / "hook.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {tool}\n{traceback.format_exc()}\n")
    except OSError:
        pass


def flush_detached() -> None:
    """The one exception to 'no subprocess': at session end the MCP server (which hosts the sender) is exiting,
    so the session's last events, including its final summary, would wait for the next session. Start one
    detached `teamloop send` that outlives this hook; Popen returns at once, so the hook stays fast."""
    if not (spool.home() / "config.json").is_file():
        return
    from teamloop import claude

    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([*claude.launcher(), "send"], **kwargs)


def deliver(tool: str, payload: dict) -> str | None:
    """Teammates' notes this live session hasn't had, as the hook's answer for Claude Code to add to what the model reads
    next. Other tools' sessions read notes with the MCP tool `read_messages`."""
    name = payload.get("hook_event_name")
    if tool != "claude_code" or name not in CONTEXT_EVENTS or not payload.get("session_id"):
        return None
    notes = messages.take(payload["session_id"])
    if not notes:
        return None
    return json.dumps({"hookSpecificOutput": {"hookEventName": name, "additionalContext": messages.frame(notes)}})


def main(tool: str) -> int:
    raw = sys.stdin.buffer.read()
    try:
        handle(tool, raw)
    except Exception:  # noqa: BLE001 - logged, never raised into the agent's session
        log(tool)
    try:
        out = deliver(tool, json.loads(raw.decode("utf-8") or "{}"))
        if out:
            sys.stdout.write(out)
    except Exception:  # noqa: BLE001 - a note that can't be delivered now waits for the next step
        log(tool)
    return 0

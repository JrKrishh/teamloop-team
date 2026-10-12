"""`teamloop hook <tool>`: hook JSON on stdin -> normalize -> redact -> spool.

Rules: no network, no subprocess, print nothing (Claude Code adds SessionStart stdout to the model's context),
and always exit 0 so a TeamLoop bug can never block the developer's session.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback

from teamloop import redact, repo, spool
from teamloop.normalize import NORMALIZERS


def handle(tool: str, raw: bytes) -> dict | None:
    if spool.paused():
        return None
    payload = json.loads(raw.decode("utf-8") or "{}")
    found = repo.find(payload.get("cwd") or os.getcwd())
    event = NORMALIZERS[tool](payload, found.root if found else None)
    if event is None:
        return None
    event["repo"] = found.root.name if found else None
    event["branch"] = repo.branch(found) if found else None
    event["task"] = repo.task(found)
    event = redact.redact_obj(event)
    spool.append(event)
    return event


def main(tool: str) -> int:
    try:
        handle(tool, sys.stdin.buffer.read())
    except Exception:  # noqa: BLE001 - logged, never raised into the agent's session
        try:
            log = spool.home() / "hook.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            with open(log, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {tool}\n{traceback.format_exc()}\n")
        except OSError:
            pass
    return 0

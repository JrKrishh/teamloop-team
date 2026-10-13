"""Blocker pings (PLAN.md S3): when an agent marks a task blocked, tell the lead where they already are.

HUB_NOTIFY_WEBHOOK is a Discord or Slack incoming-webhook URL; the payload carries both `content` (Discord) and
`text` (Slack). The reason is a teammate agent's text, so mentions are defused: Discord gets
allowed_mentions.parse = [] and every '@' gets a zero-width joiner, so '@everyone' pings nobody.
Sending happens on a background thread; a slow or dead webhook never slows the hub.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.request

log = logging.getLogger("teamloop.hub")
NEEDS = {"person": "a person", "decision": "a decision", "access": "access", "info": "information"}


def message(room: str, event: dict) -> str:
    report = event.get("report") or {}
    reason = " ".join(str(report.get("reason", "")).split())[:300].replace("@", "@‍")
    needs = NEEDS.get(report.get("needs"), "help")
    who = str(event.get("member", "someone")).replace("@", "@‍")
    return f"[TeamLoop · {room}] {event.get('task') or 'A task'} is blocked ({who}'s agent, needs {needs}): {reason}"


def _post(url: str, text: str) -> None:
    body = json.dumps({"content": text, "text": text, "allowed_mentions": {"parse": []}}).encode()
    req = urllib.request.Request(url, body, {"Content-Type": "application/json", "User-Agent": "TeamLoop-hub"})
    try:
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception as e:  # noqa: BLE001 - a ping is best-effort
        log.warning("blocker ping failed: %s", e)


def blocked(room: str, event: dict) -> None:
    url = os.getenv("HUB_NOTIFY_WEBHOOK")
    if url:
        threading.Thread(target=_post, args=(url, message(room, event)), daemon=True).start()

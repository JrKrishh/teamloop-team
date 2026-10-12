"""`teamloop mcp`: the tools an agent calls to report its own progress (PLAN.md §9.2).

Hooks see what the agent did. These tools let it say what it thinks: percent done, what's next, what blocks it.
Their text is written for the team on purpose, so it goes in `report` (shared), not `local`.
It is still redacted, capped, and labelled as the agent's own estimate.
"""

from __future__ import annotations

import os
from typing import Literal

from mcp.server.fastmcp import FastMCP

from teamloop import githook, normalize, redact, repo, spool

MAX_ITEM, MAX_ITEMS = 160, 5
mcp = FastMCP("teamloop")


def _clip(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= MAX_ITEM else text[: MAX_ITEM - 1] + "…"


def _items(items: list[str] | None) -> list[str]:
    return [_clip(i) for i in (items or []) if i and i.strip()][:MAX_ITEMS]


def _record(kind: str, facts: dict | None = None, report: dict | None = None) -> dict:
    found = repo.find(os.getcwd())
    event = normalize.event(kind, "mcp", {}, facts)
    event.update(repo=found.root.name if found else None, branch=repo.branch(found) if found else None,
                 task=repo.task(found))
    if report:
        event["report"] = report
    if spool.paused():
        return event
    spool.append(redact.redact_obj(event))
    return event


@mcp.tool()
def task_start(task_id: str, title: str = "") -> str:
    """Call this when you start working on a task, with its ID (e.g. "T-14") and a short title.
    Your team lead's board then shows the task as in progress, and your commits get tagged with it."""
    if not repo.is_task_id(task_id):
        return f"'{task_id}' is not a task ID. Use the team's format, e.g. T-14."
    if repo.find(os.getcwd()):
        githook.git("config", "teamloop.task", task_id)
    _record("task_start", {"title": _clip(title)} if title else {})
    return f"Tracking {task_id}." + (" (Sharing is paused, so nothing was recorded.)" if spool.paused() else "")


@mcp.tool()
def report_progress(percent: int, done: list[str], doing: str, next_steps: list[str]) -> str:
    """Call this after each meaningful step (a test passes, a feature works, a design is decided).
    percent: your honest estimate of how much of the current task is finished (0-100).
    done / next_steps: short bullet phrases. doing: one phrase. Only claim what you can point to (a passing test, a commit)."""
    report = {"percent": max(0, min(100, int(percent))), "done": _items(done), "doing": _clip(doing), "next": _items(next_steps)}
    event = _record("self_report", report=report)
    return f"Reported {report['percent']}% on {event['task'] or 'the current task'}."


@mcp.tool()
def mark_blocked(reason: str, needs: Literal["person", "decision", "access", "info"]) -> str:
    """Call this when you cannot proceed without help. reason: one sentence on what is blocked and why.
    needs: what would unblock you."""
    event = _record("blocked", report={"reason": _clip(reason), "needs": needs})
    return f"Marked {event['task'] or 'the current task'} as blocked; your lead will see it."


def main() -> int:
    mcp.run()
    return 0

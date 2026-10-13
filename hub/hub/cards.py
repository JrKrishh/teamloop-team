"""Events -> board cards. Pure functions, shared by the self-hosted hub (SQLite) and the cloud hub (Postgres)."""

from __future__ import annotations

from agent_s import progress


def title_for(task: str, evs: list[dict]) -> str:
    titles = [e["facts"].get("title") for e in evs if e.get("kind") == "task_start" and (e.get("facts") or {}).get("title")]
    if titles:
        return titles[-1]
    # no task_start title (e.g. Codex without MCP): fall back to the branch, T-7-multiply -> "Multiply"
    branch = next((e["branch"] for e in reversed(evs) if (e.get("branch") or "").startswith(task + "-")), "")
    words = branch[len(task) + 1:].replace("-", " ").replace("_", " ").strip()
    return words[:1].upper() + words[1:] if words else ""


def card(task: str, evs: list[dict], snap: dict | None, last_activity: float, n_events: int) -> dict:
    """One task's card. `evs` are the task's events oldest first; `snap` is Agent S's latest snapshot, if any."""
    last_block = max((e["ts"] for e in evs if e["kind"] == "blocked"), default="")
    last_move = max((e["ts"] for e in evs if e["kind"] in ("self_report", "turn_end") and e.get("status") != "blocked"),
                    default="")
    gh = {k: [e for e in evs if e["kind"] == k] for k in ("pr", "review", "check")}
    pr = gh["pr"][-1]["facts"] if gh["pr"] else None
    if last_block and last_block >= last_move:
        status = "blocked"
    elif pr and pr.get("state") == "merged":
        status = "done"
    elif pr and pr.get("state") == "open" and not pr.get("draft"):
        status = "review"
    else:
        status = (snap or {}).get("status", "in_progress")
    return {
        "task": task, "title": title_for(task, evs), "events": n_events,
        "members": sorted({e["member"] for e in evs if e["member"] != "github"}),
        "tools": sorted({e["tool"] for e in evs if e.get("tool")}),
        "pr": pr and {**pr, "checks": gh["check"][-1]["facts"].get("conclusion") if gh["check"] else None,
                      "review": gh["review"][-1]["facts"].get("state") if gh["review"] else None},
        "last_activity": last_activity, "status": status, "progress": snap,
        "recent": [{"id": e["id"], "ts": e.get("ts"), "member": e["member"], "line": progress.describe(e)}
                   for e in evs[-12:] if progress.describe(e)],
    }


def timeline(evs: list[dict]) -> list[dict]:
    """A task's events for the detail drawer, newest first, with their one-line descriptions. The session, the agent's
    report (percent, done, next, doing; or what blocks it) and turn summaries come along, so the drawer can group by
    session and show a report as rows instead of one line."""
    return [{"id": e["id"], "ts": e.get("ts"), "member": e["member"], "tool": e.get("tool"), "kind": e["kind"],
             "session": e.get("session"), "report": e.get("report"), "summary": e.get("summary"), "status": e.get("status"),
             "line": progress.describe(e)} for e in reversed(evs) if progress.describe(e)]

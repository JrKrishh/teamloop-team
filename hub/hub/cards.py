"""Events -> board cards. Pure functions, shared by the self-hosted hub (SQLite) and the cloud hub (Postgres)."""

from __future__ import annotations

from agent_s import progress

EDITING_SECONDS = 1800  # who's touching what: the files each session edited in the last half hour


def touching(evs: list[dict], now: float, window: float = EDITING_SECONDS) -> list[dict]:
    """Files edited in the last half hour, newest first: [{repo, file, who: [{member, tool, session, task, at}]}], with each
    session's latest edit. `evs` are tool events with `_at`, when the hub got them. A failed edit doesn't count."""
    files: dict[tuple, dict] = {}
    for e in evs:
        f = e.get("facts") or {}
        if e.get("kind") != "tool" or f.get("ok") is False or now - e["_at"] > window:
            continue
        for path in dict.fromkeys([f.get("file"), *(f.get("files") or [])]):
            if not isinstance(path, str) or not path:
                continue
            who = files.setdefault((e.get("repo") or "", path), {})
            key = (e.get("member"), e.get("session"))
            if key not in who or who[key]["at"] < e["_at"]:
                who[key] = {"member": e.get("member"), "tool": e.get("tool"), "session": e.get("session"),
                            "task": e.get("task"), "at": e["_at"]}
    out = [{"repo": r, "file": p, "who": sorted(w.values(), key=lambda x: -x["at"])} for (r, p), w in files.items()]
    return sorted(out, key=lambda t: -t["who"][0]["at"])


def overlaps(touch: list[dict]) -> list[dict]:
    """The files more than one session edited in that half hour: where merge conflicts start."""
    return [t for t in touch if len(t["who"]) > 1]


CLAIM_SECONDS = 24 * 3600  # a claimed task's files: what its owner edited on it in the last day


def claimed(evs: list[dict], owners: dict[str, str], now: float, window: float = CLAIM_SECONDS) -> dict[tuple, dict]:
    """(repo, file) -> {task, owner}: the files a task's owner edited on that task in the last day. `owners`: task -> the
    owner's name, for open tasks someone owns (they claimed it by starting it, or it was handed to them)."""
    out: dict[tuple, dict] = {}
    for e in sorted(evs, key=lambda e: e["_at"]):
        f, task = e.get("facts") or {}, e.get("task")
        if e.get("kind") != "tool" or f.get("ok") is False or now - e["_at"] > window or not task or owners.get(task) != e.get("member"):
            continue
        for path in dict.fromkeys([f.get("file"), *(f.get("files") or [])]):
            if isinstance(path, str) and path:
                out[(e.get("repo") or "", path)] = {"task": task, "owner": e.get("member")}
    return out


def trespass(touch: list[dict], claims: dict[tuple, dict]) -> list[dict]:
    """Recent edits to a file of a task someone else claimed, from sessions not on that task: [{repo, file, task, owner,
    who: [those edits]}]. Teammates on the same task are working together, so they don't count."""
    out = []
    for t in touch:
        c = claims.get((t["repo"], t["file"]))
        who = [w for w in t["who"] if c and w["member"] != c["owner"] and w["task"] != c["task"]]
        if who:
            out.append({"repo": t["repo"], "file": t["file"], **c, "who": who})
    return out


def editing(touch: list[dict], task: str) -> list[dict]:
    """A task's files being edited now, for its card."""
    return [{"repo": t["repo"], "file": t["file"], "member": w["member"], "tool": w["tool"]}
            for t in touch for w in t["who"] if w["task"] == task][:6]


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

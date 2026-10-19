"""`teamloop pushed <remote> [url]`: the pre-push hook's half. Which of the team's agents' commits a push shares, as one
event per branch: each commit's sha, subject (redacted), task and files with line counts, never a diff or file contents.
A commit made by hand has no TeamLoop-Task link (AGENTS.md rule 9) and isn't in it. Commits are the team's from the
push on, so nothing unpushed leaves the laptop. Like a hook, it never fails a push: errors go to hook.log.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from teamloop import normalize, redact, repo, spool

MAX_COMMITS, MAX_FILES = 50, 40


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          stdin=subprocess.DEVNULL).stdout


def commits(root: Path, remote: str, local_sha: str, remote_sha: str) -> list[str]:
    """The commits this push adds to the remote, oldest first."""
    if set(remote_sha) == {"0"}:  # a new branch: what no branch of that remote has yet
        out = _git(root, "rev-list", "--reverse", f"--max-count={MAX_COMMITS}", local_sha, "--not", f"--remotes={remote}")
    else:
        out = _git(root, "rev-list", "--reverse", f"--max-count={MAX_COMMITS}", f"{remote_sha}..{local_sha}")
    return out.split()


def describe(root: Path, sha: str) -> dict | None:
    """An agent's commit as the team sees it; None for one made by hand."""
    subject, _, task = _git(root, "log", "-1", "--format=%s%x00%(trailers:key=TeamLoop-Task,valueonly,separator=%x2C)", sha) \
        .strip().partition("\x00")
    task = task.split(",")[0].strip()
    if not repo.is_task_id(task):
        return None
    files = []
    for line in _git(root, "diff-tree", "--no-commit-id", "--numstat", "-r", "--root", sha).splitlines()[:MAX_FILES]:
        added, deleted, path = (line.split("\t", 2) + ["", "", ""])[:3]
        if path:
            files.append({"path": path, "add": int(added) if added.isdigit() else 0, "del": int(deleted) if deleted.isdigit() else 0})
    return {"sha": sha[:12], "subject": redact.redact(subject)[:160], "task": task, "files": files}


def record(where: str | os.PathLike, remote: str, lines: list[str]) -> list[dict]:
    """The push events for the pre-push hook's input, spooled: one per branch that shares an agent's commits."""
    from teamloop import workspace

    found = repo.find(where)
    if found is None or spool.paused():
        return []
    try:
        workspace.remember(found.root)
    except Exception:  # noqa: BLE001 - never at the cost of the push event
        pass
    events = []
    for line in lines:
        parts = line.split()
        if len(parts) != 4 or set(parts[1]) == {"0"} or not parts[2].startswith("refs/heads/"):
            continue  # not a branch update (a delete, a tag)
        branch = parts[2].removeprefix("refs/heads/")
        shared = [c for c in (describe(found.root, s) for s in commits(found.root, remote, parts[1], parts[3])) if c]
        if not shared:
            continue
        tasks = {c["task"] for c in shared}
        event = normalize.event("push", "git", {}, {"commits": len(shared)})
        event.update(repo=found.root.name, branch=branch, task=tasks.pop() if len(tasks) == 1 else None,
                     push={"branch": branch, "commits": shared})
        event = redact.redact_obj(event)
        spool.append(event)
        events.append(event)
    return events


def main(remote: str) -> int:
    from teamloop import hook

    try:
        if record(os.getcwd(), remote, sys.stdin.read().splitlines()):
            hook.flush_detached()  # no session may be running to send it: one detached `teamloop send`
    except Exception:  # noqa: BLE001 - logged, never in the way of a push
        hook.log("pushed")
    return 0

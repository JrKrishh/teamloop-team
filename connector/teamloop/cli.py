"""`teamloop` command line. Day 1: hook, task, git-hook, pause/resume, status (login/init/doctor/daemon come next)."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from teamloop import __version__


def _task(args: argparse.Namespace) -> int:
    from teamloop import githook, normalize, redact, repo, spool

    if args.clear:
        subprocess.run(["git", "config", "--unset", "teamloop.task"], check=False)
        print("task cleared")
        return 0
    if not args.id:
        found = repo.find(os.getcwd())
        print(repo.task(found) or "no task set (teamloop task <ID>)")
        return 0
    if not is_task_id(args.id):
        print(f"not a task id: {args.id} (expected something like T-14)", file=sys.stderr)
        return 2
    githook.git("config", "teamloop.task", args.id)
    found = repo.find(os.getcwd())
    event = normalize.event("task_start", "cli", {}, {"title": args.title} if args.title else {})
    event.update(repo=found.root.name if found else None, branch=repo.branch(found) if found else None, task=args.id)
    spool.append(redact.redact_obj(event))
    print(f"working on {args.id}" + (f": {args.title}" if args.title else ""))
    return 0


def is_task_id(task_id: str) -> bool:
    from teamloop.repo import TASK_ID

    return bool(TASK_ID.fullmatch(task_id))


def _status(_: argparse.Namespace) -> int:
    from teamloop import repo, spool

    found = repo.find(os.getcwd())
    print(f"teamloop {__version__}")
    print(f"sharing:  {'PAUSED' if spool.paused() else 'on'}")
    print(f"spool:    {len(spool.pending())} event(s) waiting in {spool.spool_dir()}")
    print(f"repo:     {found.root.name if found else '(not in a git repo)'}")
    print(f"task:     {repo.task(found) or '(none)'}")
    return 0


def _pause(args: argparse.Namespace) -> int:
    from teamloop import spool

    flag = spool.home() / "paused"
    if args.cmd == "pause":
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.touch()
        print("sharing paused: hooks record nothing until `teamloop resume`")
    else:
        flag.unlink(missing_ok=True)
        print("sharing resumed")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="teamloop", description="Your AI coding session's progress, shared with your team as summaries.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("hook", help="called by your coding tool's hooks; reads the event on stdin")
    h.add_argument("tool", choices=["claude_code"])
    t = sub.add_parser("task", help="set the task this repo is working on, e.g. `teamloop task T-14 \"Add SSE\"`")
    t.add_argument("id", nargs="?")
    t.add_argument("title", nargs="?")
    t.add_argument("--clear", action="store_true")
    g = sub.add_parser("git-hook", help="install the commit hook that adds TeamLoop-Task trailers")
    g.add_argument("action", choices=["install"])
    sub.add_parser("pause", help="stop recording anything")
    sub.add_parser("resume", help="start recording again")
    sub.add_parser("status", help="show sharing state, spool and current task")
    args = ap.parse_args(argv)

    if args.cmd == "hook":
        from teamloop import hook

        return hook.main(args.tool)
    if args.cmd == "task":
        return _task(args)
    if args.cmd == "git-hook":
        from teamloop import githook

        print(githook.install())
        return 0
    if args.cmd in ("pause", "resume"):
        return _pause(args)
    return _status(args)

"""`teamloop` command line."""

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
    if not repo.is_task_id(args.id):
        print(f"not a task id: {args.id} (expected something like T-14)", file=sys.stderr)
        return 2
    githook.git("config", "teamloop.task", args.id)
    found = repo.find(os.getcwd())
    event = normalize.event("task_start", "cli", {}, {"title": args.title} if args.title else {})
    event.update(repo=found.root.name if found else None, branch=repo.branch(found) if found else None, task=args.id)
    spool.append(redact.redact_obj(event))
    print(f"working on {args.id}" + (f": {args.title}" if args.title else ""))
    return 0


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
    sub = ap.add_subparsers(dest="cmd")  # no command = open the board (double-click, Start menu)
    h = sub.add_parser("hook", help="called by your coding tool's hooks; reads the event on stdin")
    h.add_argument("tool", choices=["claude_code", "codex"])
    t = sub.add_parser("task", help="set the task this repo is working on, e.g. `teamloop task T-14 \"Add SSE\"`")
    t.add_argument("id", nargs="?")
    t.add_argument("title", nargs="?")
    t.add_argument("--clear", action="store_true")
    g = sub.add_parser("git-hook", help="install the commit hook that adds TeamLoop-Task trailers")
    g.add_argument("action", choices=["install"])
    sub.add_parser("pause", help="stop recording anything")
    sub.add_parser("resume", help="start recording again")
    sub.add_parser("status", help="show sharing state, spool and current task")
    i = sub.add_parser("init", help="connect Claude Code (hooks + MCP) and the commit hook for this repo")
    i.add_argument("--scope", choices=["local", "user"], default="local", help="local: this repo only (default); user: every repo")
    i.add_argument("--dry-run", action="store_true")
    sub.add_parser("doctor", help="check that everything is wired, with the fix for each problem")
    sub.add_parser("mcp", help="run the MCP server (your coding tool starts this, not you)")
    lg = sub.add_parser("login", help="join your team's hub with the invite your lead shared")
    lg.add_argument("invite")
    lg.add_argument("--name", help="how you appear to the team (default: your OS user name)")
    inv = sub.add_parser("invite", help="(lead) make an invite for a hub room")
    inv.add_argument("--url", required=True)
    inv.add_argument("--room", required=True)
    inv.add_argument("--token", help="room token (default: a new random one)")
    hb = sub.add_parser("hub", help="(lead) run your team's hub and board on this machine")
    hb.add_argument("--port", type=int, default=8799)
    hb.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to let teammates on your LAN reach it")
    hb.add_argument("--room", default="teamloop")
    hb.add_argument("--public-url", help="the https URL teammates use (e.g. a cloudflared tunnel); goes into the invite")
    hb.add_argument("--no-browser", action="store_true")
    hb.add_argument("--demo", action="store_true", help="also serve the public sample room")
    sub.add_parser("send", help="summarize and send everything waiting in the spool, once")
    sub.add_parser("daemon", help="keep sending in the background (every 5 s, backs off when the hub is down)")
    args = ap.parse_args(argv)
    if args.cmd is None:
        from teamloop import launch

        return launch.run()

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
    if args.cmd == "init":
        from teamloop import init

        return init.run(args.scope, args.dry_run)
    if args.cmd == "doctor":
        from teamloop import doctor

        return doctor.run()
    if args.cmd == "mcp":
        from teamloop import mcp_server

        return mcp_server.main()
    if args.cmd == "login":
        from teamloop import login

        return login.login(args.invite, args.name)
    if args.cmd == "invite":
        from teamloop import login

        print(login.invite(args.url, args.room, args.token))
        return 0
    if args.cmd == "hub":
        from teamloop import hubcmd

        return hubcmd.run(args.port, args.host, args.room, args.public_url, not args.no_browser, args.demo)
    if args.cmd in ("send", "daemon"):
        from teamloop import send

        return send.main(once=args.cmd == "send")
    return _status(args)

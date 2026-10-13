"""`teamloop doctor`: is everything wired? Every problem comes with the exact command that fixes it."""

from __future__ import annotations

import os
import platform
import re
import time
from pathlib import Path

from teamloop import __version__, claude, codex, githook, repo, spool


def checks(cwd: Path) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    add = lambda level, msg, fix="": rows.append((level, msg, fix))  # noqa: E731
    add("ok", f"teamloop {__version__}, Python {platform.python_version()}")

    try:
        d = spool.spool_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / ".probe").write_text("x")
        (d / ".probe").unlink()
        add("ok", f"spool writable ({d})")
    except OSError as e:
        add("fail", f"spool not writable: {e}", "check permissions on ~/.teamloop")
    if spool.paused():
        add("warn", "sharing is paused: nothing is recorded", "teamloop resume")

    found = repo.find(cwd)
    if found is None:
        add("warn", "not in a git repo", "cd into your project")
    else:
        task = repo.task(found)
        add("ok", f"task {task}") if task else add("warn", "no task set", 'teamloop task T-<id> "title"')
        hook = githook.hooks_dir(found.root) / githook.NAME
        if hook.is_file() and githook.MARK in hook.read_text(encoding="utf-8", errors="replace"):
            add("ok", "commit hook installed")
        else:
            add("fail", "commit hook missing", "teamloop git-hook install")

    scopes = {"local": found.root if found else None, "user": None}
    wired = []
    for scope, root in scopes.items():
        if scope == "local" and root is None:
            continue
        path = claude.settings_path(scope, root)
        try:
            settings = claude.load(path)
        except ValueError:
            add("fail", f"{path} is not valid JSON", "fix the file, then teamloop init")
            continue
        if not claude.missing(settings):
            wired.append((scope, settings))
    if not wired:
        add("fail", "Claude Code hooks not set up", "teamloop init")
    else:
        scope, settings = wired[0]
        cmd = next(h["command"] for g in settings["hooks"]["SessionStart"] for h in g["hooks"] if claude.ours(h))
        exe = re.match(r'"([^"]+)"', cmd)
        if exe and not Path(exe.group(1)).exists():
            add("fail", f"Claude Code hooks point to a missing Python: {exe.group(1)}", "teamloop init")
        else:
            add("ok", f"Claude Code hooks on all {len(claude.EVENTS)} events ({scope} settings)")

    registered = claude.mcp_registered(found.root if found else cwd)
    if registered is None:
        add("warn", "claude CLI not on PATH, so the MCP server can't be checked")
    elif registered:
        add("ok", "MCP server 'teamloop' registered")
    else:
        add("fail", "MCP server not registered", "teamloop init")

    if codex.cli():
        paths = [codex.hooks_path("local", found.root)] if found else []
        paths.append(codex.hooks_path("user", None))
        try:
            wired_codex = any(not claude.missing(claude.load(p), codex.EVENTS, codex.TAG) for p in paths)
        except ValueError:
            wired_codex = False
        if wired_codex:
            add("ok", f"Codex hooks on all {len(codex.EVENTS)} events (approve them once in Codex: /hooks)")
        else:
            add("fail", "Codex is installed but its hooks aren't set up", "teamloop init")
        if codex.mcp_registered():
            add("ok", "Codex MCP server 'teamloop' registered")
        else:
            add("fail", "Codex MCP server not registered", "teamloop init")

    log = spool.home() / "hook.log"
    if log.is_file() and time.time() - log.stat().st_mtime < 86400:
        last = [l for l in log.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()][-1:]
        add("warn", f"hook errors in the last 24 h: {last[0][:100] if last else ''}", f"see {log}")
    pending = spool.pending()
    if pending:
        age = (time.time_ns() - int(pending[-1].name.split("-")[0])) / 1e9
        add("ok", f"last event recorded {_ago(age)} ago; {len(pending)} waiting to send")
    else:
        add("warn", "no events recorded yet", "start a Claude Code session in this repo")

    if os.environ.get("NEBIUS_API_KEY"):
        add("ok", "NEBIUS_API_KEY set")
    else:
        add("warn", "NEBIUS_API_KEY not set: turn summaries need it", "set NEBIUS_API_KEY")
    from teamloop import send

    cfg = send.config()
    if cfg:
        add("ok", f"connected to {cfg.get('url')} as {cfg.get('name')} (room {cfg.get('room')})")
    else:
        add("warn", "not connected to a team hub, so nothing is shared yet", "teamloop login <invite from your lead>")
    return rows


def _ago(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f} s"
    if seconds < 5400:
        return f"{seconds / 60:.0f} min"
    return f"{seconds / 3600:.1f} h"


def run() -> int:
    rows = checks(Path.cwd())
    width = max(len(m) for _, m, _ in rows)
    for level, msg, fix in rows:
        print((f"  {level:<5} {msg:<{width}}   -> {fix}" if fix else f"  {level:<5} {msg}"))
    failed = sum(level == "fail" for level, _, _ in rows)
    print(f"\n{failed} problem(s)." if failed else "\nAll set.")
    return 1 if failed else 0

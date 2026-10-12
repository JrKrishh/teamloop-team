"""Claude Code wiring: which hooks we register, where settings live, and how to merge without clobbering."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

# event -> matcher (None for events that take no matcher)
EVENTS = {"SessionStart": None, "PostToolUse": "*", "PostToolUseFailure": "*", "Notification": None,
          "Stop": None, "SubagentStop": None, "SessionEnd": None}
TAG = "-m teamloop hook claude_code"


def python() -> str:
    return Path(sys.executable).as_posix()  # forward slashes work in both bash and cmd


def hook_command() -> str:
    return f'"{python()}" {TAG}'


def settings_path(scope: str, repo_root: Path | None) -> Path:
    if scope == "user":
        return Path.home() / ".claude" / "settings.json"
    if repo_root is None:
        raise ValueError("local scope needs a git repo; run inside one or use --scope user")
    return repo_root / ".claude" / "settings.local.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def ours(hook: dict) -> bool:
    return TAG in (hook.get("command") or "")


def merge(settings: dict, command: str) -> list[str]:
    """Add or update our hook on every event; leave everyone else's hooks alone. Returns what changed."""
    changes = []
    hooks = settings.setdefault("hooks", {})
    for event, matcher in EVENTS.items():
        groups = hooks.setdefault(event, [])
        mine = [h for g in groups for h in g.get("hooks", []) if ours(h)]
        if mine:
            for h in mine:
                if h.get("command") != command:
                    h["command"] = command
                    changes.append(f"updated {event}")
            continue
        group = {"hooks": [{"type": "command", "command": command, "timeout": 10}]}
        groups.append({"matcher": matcher, **group} if matcher else group)
        changes.append(f"added {event}")
    return changes


def missing(settings: dict) -> list[str]:
    hooks = settings.get("hooks", {})
    return [e for e in EVENTS if not any(ours(h) for g in hooks.get(e, []) for h in g.get("hooks", []))]


def cli() -> str | None:
    return shutil.which("claude")


def mcp_registered(cwd: Path) -> bool | None:
    """True/False from `claude mcp get teamloop`; None when the claude CLI isn't installed."""
    exe = cli()
    if not exe:
        return None
    r = subprocess.run([exe, "mcp", "get", "teamloop"], cwd=cwd, capture_output=True, text=True, timeout=60)
    return r.returncode == 0


def register_mcp(cwd: Path, scope: str) -> str:
    exe = cli()
    if not exe:
        return "skipped MCP: the claude CLI is not on PATH"
    if mcp_registered(cwd):
        return "MCP server already registered"
    r = subprocess.run([exe, "mcp", "add", "--scope", scope, "teamloop", "--", python(), "-m", "teamloop", "mcp"],
                       cwd=cwd, capture_output=True, text=True, timeout=60)
    return "registered MCP server 'teamloop'" if r.returncode == 0 else f"MCP registration failed: {r.stderr.strip()[:200]}"

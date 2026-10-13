"""Codex CLI wiring. Learned from real runs (13 Oct 2026, Codex 0.162.1 on Windows):
- hooks.json has Claude Code's shape, so claude.merge/missing are reused with Codex's events;
- on Windows Codex runs hook commands through PowerShell, where a command starting with a quoted path is a
  syntax error and the hook silently fails. Unquoted paths work; paths with spaces need PowerShell's `&`;
- hooks from a repo need the user's one-time trust in Codex's /hooks screen;
- `codex mcp add` only writes the user-level ~/.codex/config.toml.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from teamloop import claude

EVENTS = {"SessionStart": None, "PostToolUse": None, "PermissionRequest": None, "Stop": None,
          "SubagentStop": None, "SessionEnd": None}
TAG = "hook codex"


def hook_command() -> str:
    exe, *rest = claude.launcher()
    tail = " ".join([*rest, TAG])
    if " " not in exe:
        return f"{exe} {tail}"
    return f'& "{exe}" {tail}' if os.name == "nt" else f'"{exe}" {tail}'


def hooks_path(scope: str, repo_root: Path | None) -> Path:
    if scope == "user":
        return Path.home() / ".codex" / "hooks.json"
    if repo_root is None:
        raise ValueError("local scope needs a git repo")
    return repo_root / ".codex" / "hooks.json"


def cli() -> str | None:
    return shutil.which("codex")


def mcp_registered() -> bool | None:
    exe = cli()
    if not exe:
        return None
    r = subprocess.run([exe, "mcp", "get", "teamloop"], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    return r.returncode == 0


def register_mcp() -> str:
    exe = cli()
    if not exe:
        return "skipped: codex is not on PATH"
    if mcp_registered():
        return "MCP server already registered"
    r = subprocess.run([exe, "mcp", "add", "teamloop", "--", *claude.launcher(), "mcp"],
                       capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    return "registered MCP server 'teamloop' (user-level ~/.codex/config.toml)" if r.returncode == 0 \
        else f"MCP registration failed: {r.stderr.strip()[:200]}"

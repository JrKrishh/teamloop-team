"""The `prepare-commit-msg` hook that links commits an AI coding agent makes to their task (PLAN.md §9.3):
`TeamLoop-Task: <id>`. Commits made by hand are left alone, so the trailer also says an agent made the commit: Super Team
follows agents' work. Nothing names the agent in the message (no attribution line).

How it tells (checked in each tool's build, 19 Oct): Claude Code sets CLAUDECODE=1 and Cursor CURSOR_AGENT=1 for the
commands their agents run; Super Agents' own agents set TEAMLOOP_AGENT. Codex sets no such variable, so `teamloop
agent-of` looks for a Codex process among the ones that started the commit.
prepare-commit-msg runs even with `git commit --no-verify`. An existing hook is kept and still runs first.
"""

from __future__ import annotations

import os
import shlex
import stat
import subprocess
from pathlib import Path

MARK = "# teamloop prepare-commit-msg"
NAME = "prepare-commit-msg"
KEPT = NAME + ".pre-teamloop"
PUSH_MARK, PUSH_NAME = "# teamloop pre-push", "pre-push"
PUSH_KEPT = PUSH_NAME + ".pre-teamloop"


def push_script() -> str:
    """pre-push: tells the team which of its agents' commits this push shares (`teamloop pushed`, see pushed.py). It never
    stops a push; a hook that was there first still runs first, with the same input, and can."""
    from teamloop import claude

    exe, *rest = claude.launcher()
    pushed = " ".join(shlex.quote(p) for p in [Path(exe).as_posix(), *rest, "pushed"])
    return f"""#!/bin/sh
{PUSH_MARK}: tells the team which of its agents' commits a push shares. Installed by `teamloop git-hook install`.
KEPT="$(dirname "$0")/{PUSH_KEPT}"
IN=$(cat)
if [ -f "$KEPT" ]; then printf '%s\\n' "$IN" | "$KEPT" "$@" || exit $?; fi
printf '%s\\n' "$IN" | {pushed} "$@" >/dev/null 2>&1
exit 0
"""


def script() -> str:
    from teamloop import claude

    exe, *rest = claude.launcher()
    agent_of = " ".join(shlex.quote(p) for p in [Path(exe).as_posix(), *rest, "agent-of"])
    return f"""#!/bin/sh
{MARK}: links commits an AI coding agent makes to their task. Installed by `teamloop git-hook install`.
KEPT="$(dirname "$0")/{KEPT}"
if [ -f "$KEPT" ]; then "$KEPT" "$@" || exit $?; fi
case "$2" in merge|squash) exit 0;; esac
if [ "$CLAUDECODE" != 1 ] && [ "$CURSOR_AGENT" != 1 ] && [ -z "$TEAMLOOP_AGENT" ] && [ -z "$({agent_of} 2>/dev/null)" ]; then
  exit 0  # made by hand
fi
TASK="${{TEAMLOOP_TASK:-$(git config --get teamloop.task)}}"
[ -z "$TASK" ] && TASK=$(git symbolic-ref --quiet --short HEAD | grep -oE '[A-Z][A-Z0-9]*-[0-9]+' | head -1)
[ -n "$TASK" ] && git interpret-trailers --in-place --if-exists=doNothing --trailer "TeamLoop-Task: $TASK" "$1"
exit 0
"""


def git(*args: str, cwd: str | os.PathLike = ".") -> str:
    # stdin=DEVNULL: inside the MCP server, stdin is the protocol pipe; a child that inherits it stalls on Windows
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL).stdout.strip()


def hooks_dir(cwd: str | os.PathLike = ".") -> Path:
    """Where git really runs hooks from (honours core.hooksPath and worktrees)."""
    d = Path(git("rev-parse", "--git-path", "hooks", cwd=cwd))
    return d if d.is_absolute() else Path(cwd) / d


def _put(d: Path, name: str, mark: str, kept: str, text: str) -> str:
    hook = d / name
    if hook.exists():
        if mark in hook.read_text(encoding="utf-8", errors="replace"):
            result = "already installed"
        else:
            hook.replace(d / kept)
            result = f"installed; your existing hook was kept as {kept} and still runs first"
    else:
        result = "installed"
    hook.write_text(text, encoding="utf-8", newline="\n")  # an older TeamLoop hook is brought up to date
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return result


def install(cwd: str | os.PathLike = ".") -> str:
    d = hooks_dir(cwd)
    d.mkdir(parents=True, exist_ok=True)
    result = _put(d, NAME, MARK, KEPT, script())
    _put(d, PUSH_NAME, PUSH_MARK, PUSH_KEPT, push_script())
    return f"{result}: {d / NAME} (and {PUSH_NAME})"


def current(cwd: str | os.PathLike = ".") -> bool | None:
    """Whether this repo's hooks are TeamLoop's current ones (None: not TeamLoop's), for `teamloop doctor`."""
    d = hooks_dir(cwd)
    text, push = ((d / n).read_text(encoding="utf-8", errors="replace") if (d / n).is_file() else "" for n in (NAME, PUSH_NAME))
    return None if MARK not in text else "CLAUDECODE" in text and PUSH_MARK in push


def processes() -> dict[int, tuple[int, str]]:
    """pid -> (parent pid, executable name, lower case): a snapshot of the running processes."""
    out: dict[int, tuple[int, str]] = {}
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class Entry(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                        ("szExeFile", ctypes.c_wchar * 260)]
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k32.Process32FirstW.argtypes = k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
        if snap in (None, wintypes.HANDLE(-1).value):
            return out
        e = Entry()
        e.dwSize = ctypes.sizeof(Entry)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            out[e.th32ProcessID] = (e.th32ParentProcessID, e.szExeFile.lower())
            ok = k32.Process32NextW(snap, ctypes.byref(e))
        k32.CloseHandle(snap)
        return out
    r = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,comm="], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    for line in r.stdout.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            out[int(parts[0])] = (int(parts[1]), os.path.basename(parts[2]).lower())
    return out


def agent_of(pid: int | None = None, procs: dict[int, tuple[int, str]] | None = None) -> str | None:
    """'codex' when a Codex process (codex, codex-command-runner) started this one, else None."""
    procs = processes() if procs is None else procs
    pid, seen = os.getpid() if pid is None else pid, set()
    while pid in procs and pid not in seen:
        seen.add(pid)
        parent, name = procs[pid]
        if name.startswith("codex"):
            return "codex"
        pid = parent
    return None

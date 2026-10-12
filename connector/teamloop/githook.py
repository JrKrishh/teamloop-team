"""The `prepare-commit-msg` hook that adds `TeamLoop-Task: <id>` to commits (PLAN.md §9.3).

prepare-commit-msg runs even with `git commit --no-verify`. An existing hook is kept and still runs first.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

MARK = "# teamloop prepare-commit-msg"
NAME = "prepare-commit-msg"
KEPT = NAME + ".pre-teamloop"

SCRIPT = f"""#!/bin/sh
{MARK}: adds a TeamLoop-Task trailer. Installed by `teamloop git-hook install`.
KEPT="$(dirname "$0")/{KEPT}"
if [ -f "$KEPT" ]; then "$KEPT" "$@" || exit $?; fi
case "$2" in merge|squash) exit 0;; esac
TASK="${{TEAMLOOP_TASK:-$(git config --get teamloop.task)}}"
[ -z "$TASK" ] && TASK=$(git symbolic-ref --quiet --short HEAD | grep -oE '[A-Z][A-Z0-9]*-[0-9]+' | head -1)
[ -n "$TASK" ] && git interpret-trailers --in-place --if-exists=doNothing --trailer "TeamLoop-Task: $TASK" "$1"
exit 0
"""


def git(*args: str, cwd: str | os.PathLike = ".") -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def hooks_dir(cwd: str | os.PathLike = ".") -> Path:
    """Where git really runs hooks from (honours core.hooksPath and worktrees)."""
    d = Path(git("rev-parse", "--git-path", "hooks", cwd=cwd))
    return d if d.is_absolute() else Path(cwd) / d


def install(cwd: str | os.PathLike = ".") -> str:
    d = hooks_dir(cwd)
    d.mkdir(parents=True, exist_ok=True)
    hook = d / NAME
    if hook.exists():
        if MARK in hook.read_text(encoding="utf-8", errors="replace"):
            result = "already installed"
        else:
            hook.replace(d / KEPT)
            result = f"installed; your existing hook was kept as {KEPT} and still runs first"
    else:
        result = "installed"
    hook.write_text(SCRIPT, encoding="utf-8", newline="\n")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return f"{result}: {hook}"

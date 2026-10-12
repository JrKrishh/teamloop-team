"""Repo facts read straight from .git files. The hook never spawns git: session-end budgets are 1-1.5 s."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

TASK_ID = re.compile(r"[A-Z][A-Z0-9]*-\d+")


@dataclass
class Repo:
    root: Path
    git_dir: Path      # per-worktree: HEAD lives here
    common_dir: Path   # shared: config lives here


def find(start: str | os.PathLike) -> Repo | None:
    here = Path(start).absolute()
    for d in (here, *here.parents):
        dot = d / ".git"
        if dot.is_dir():
            return Repo(d, dot, dot)
        if dot.is_file():  # a worktree or submodule: ".git" is a "gitdir: <path>" file
            text = dot.read_text(encoding="utf-8").strip()
            if not text.startswith("gitdir:"):
                return None
            git_dir = _under(d, text[len("gitdir:"):].strip())
            common = git_dir
            if (git_dir / "commondir").is_file():
                common = _under(git_dir, (git_dir / "commondir").read_text(encoding="utf-8").strip())
            return Repo(d, git_dir, common)
    return None


def _under(base: Path, p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (base / path).resolve()


def branch(repo: Repo) -> str | None:
    try:
        head = (repo.git_dir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    prefix = "ref: refs/heads/"
    return head[len(prefix):] if head.startswith(prefix) else None  # None when detached


def configured_task(repo: Repo) -> str | None:
    """`git config teamloop.task T-14` writes "[teamloop]\\n\\ttask = T-14" to the repo config."""
    try:
        config = (repo.common_dir / "config").read_text(encoding="utf-8")
    except OSError:
        return None
    section = re.search(r"^\[teamloop\]\s*$(.*?)(?=^\s*\[|\Z)", config, re.M | re.S | re.I)
    if not section:
        return None
    task = re.search(r"^\s*task\s*=\s*(\S+)\s*$", section.group(1), re.M | re.I)
    return task.group(1) if task else None


def task(repo: Repo | None) -> str | None:
    """Same order as the git trailer hook: $TEAMLOOP_TASK, then `git config teamloop.task`, then the branch name."""
    if os.environ.get("TEAMLOOP_TASK"):
        return os.environ["TEAMLOOP_TASK"]
    if repo is None:
        return None
    found = configured_task(repo)
    if found:
        return found
    m = TASK_ID.search(branch(repo) or "")
    return m.group(0) if m else None

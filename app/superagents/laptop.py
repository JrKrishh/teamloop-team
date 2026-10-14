"""This laptop, as the app sees it: which team it reports to, whether sharing is on, which repos are connected and
what is waiting to send. Everything here is the connector's own code (teamloop.*); the app only calls it."""

from __future__ import annotations

import contextlib
import io
import time
from pathlib import Path

from teamloop import claude, codex, init, login, repo, send, spool

from . import store


def _hooked(path: Path, events: dict, tag: str) -> bool:
    try:
        return not claude.missing(claude.load(path), events, tag)
    except (OSError, ValueError):
        return False


def repo_status(path: str) -> dict:
    found = repo.find(path) if Path(path).is_dir() else None
    if not found:
        return {"path": path, "name": Path(path).name, "ok": False, "claude_code": False, "codex": None}
    has_codex = codex.cli() is not None
    return {"path": str(found.root), "name": found.root.name, "ok": True,
            "claude_code": _hooked(claude.settings_path("local", found.root), claude.EVENTS, claude.TAG),
            "codex": _hooked(codex.hooks_path("local", found.root), codex.EVENTS, codex.TAG) if has_codex else None,
            "task": repo.task(found)}


def status() -> dict:
    cfg = send.config() or {}
    pending = spool.pending()
    age = (time.time_ns() - int(pending[-1].name.split("-")[0])) / 1e9 if pending else None
    return {"team": cfg.get("team") if cfg.get("mode") == "cloud" else None,
            "name": cfg.get("name") if cfg.get("mode") == "cloud" else None,
            "self_hosted": cfg.get("url") if cfg and cfg.get("mode") != "cloud" else None,
            "paused": spool.paused(), "pending": len(pending), "oldest_pending_s": age,
            "tools": {"claude_code": claude.cli() is not None, "codex": codex.cli() is not None},
            "repos": [repo_status(p) for p in store.repos()]}


def connect_team(cloud_url: str, link: dict) -> None:
    """Point this laptop's hooks and MCP server at a team, with the connector token the hub just made for it."""
    login.save({"mode": "cloud", "url": cloud_url, "token": link["token"], "name": link["name"], "team": link["team"]})


def disconnect() -> None:
    """Signing out of the app stops this laptop from reporting under your name."""
    cfg = send.config() or {}
    if cfg.get("mode") == "cloud":
        (spool.home() / "config.json").unlink(missing_ok=True)


def connect_repo(path: str) -> dict:
    """`teamloop init` for the folder you picked: Claude Code (and Codex) hooks, MCP server, commit hook."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = init.run("local", False, where=Path(path))
    found = repo.find(path)
    if code == 0 and found:
        store.add_repo(str(found.root))
    return {"ok": code == 0, "log": out.getvalue().strip(), "repo": repo_status(str(found.root) if found else path)}


def set_paused(paused: bool) -> None:
    flag = spool.home() / "paused"
    if paused:
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.touch()
    else:
        flag.unlink(missing_ok=True)


def send_now() -> dict:
    sent, error = send.send_once()
    return {"sent": sent, "error": error}

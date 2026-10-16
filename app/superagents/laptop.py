"""This laptop, as the app sees it: which team it reports to, whether sharing is on, which repos are connected and
what is waiting to send. Everything here is the connector's own code (teamloop.*); the app only calls it."""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from teamloop import claude, codex, init, login, normalize, redact, repo, send, spool

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


def _git_out(*args: str, cwd: str | None = None) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def git_info(repos: list[dict]) -> dict:
    """Git on this laptop, for committing and pushing like Claude Code: git itself, the credential helper that signs
    in to GitHub (Git Credential Manager comes with Git for Windows), the GitHub CLI for pull requests, and each
    connected repo's origin (so the app can tell which team projects are already here)."""
    found = shutil.which("git") is not None
    return {"git": found, "helper": _git_out("config", "--get", "credential.helper") if found else "",
            "gh": shutil.which("gh") is not None,
            "origins": {r["path"]: _git_out("remote", "get-url", "origin", cwd=r["path"]) for r in repos if r["ok"] and found}}


GITHUB_API = "https://api.github.com"


def github_repos(run=subprocess.run, fetch=None) -> dict:
    """The GitHub repos this laptop's GitHub sign-in can open, most recently pushed first: through the GitHub CLI when
    it's signed in, otherwise with the token Git Credential Manager keeps for github.com (it never leaves this
    function). Raises LookupError when neither is signed in."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never", "GH_PROMPT_DISABLED": "1"}
    query = "user/repos?per_page=100&sort=pushed&affiliation=owner,collaborator,organization_member"
    found: list[dict] = []
    if shutil.which("gh"):
        for page in (1, 2, 3):
            r = run(["gh", "api", f"{query}&page={page}"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=60, stdin=subprocess.DEVNULL, env=env)
            if r.returncode != 0:
                break
            batch = json.loads(r.stdout or "[]")
            found += batch
            if len(batch) < 100:
                return {"via": "gh", "repos": _repo_list(found)}
        if found:
            return {"via": "gh", "repos": _repo_list(found)}
    r = run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n", capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=20, env=env)
    token = next((line[9:] for line in (r.stdout or "").splitlines() if line.startswith("password=")), "") if r.returncode == 0 else ""
    if not token:
        raise LookupError("Sign in to GitHub on this laptop first: install the GitHub CLI and run `gh auth login`, "
                          "or clone any private GitHub repo once so Git Credential Manager keeps your sign-in.")
    fetch = fetch or _github_get
    for page in (1, 2, 3):
        batch = fetch(f"{GITHUB_API}/{query}&page={page}", token)
        found += batch
        if len(batch) < 100:
            break
    return {"via": "git", "repos": _repo_list(found)}


def _github_get(url: str, token: str) -> list:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                               "User-Agent": "SuperAgents"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise LookupError("GitHub didn't accept this laptop's sign-in: sign in again with `gh auth login`."
                          if e.code == 401 else f"GitHub answered {e.code}.") from None


def _repo_list(items: list) -> list[dict]:
    return [{"name": it["full_name"], "url": it["html_url"], "private": bool(it.get("private")),
             "description": it.get("description") or "", "pushed": it.get("pushed_at") or it.get("updated_at") or ""}
            for it in items if isinstance(it, dict) and it.get("full_name") and it.get("html_url")]


def clone(url: str, parent: str) -> dict:
    """Get a team project: clone it into a new folder under the one picked, with this laptop's own GitHub sign-in,
    then connect it like Connect a repo does."""
    name = re.sub(r"\.git$", "", re.split(r"[/\\:]", url.rstrip("/\\"))[-1])
    target = Path(parent) / name
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"{target} already exists and isn't empty; pick another folder")
    r = subprocess.run(["git", "clone", url, str(target)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=900, stdin=subprocess.DEVNULL, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[-800:] or "git clone failed")
    return {"path": str(target), **connect_repo(str(target))}


def start_task(path: str, task: str, title: str) -> dict:
    """What `teamloop task T-23 "title"` does, for a repo the app connected: sessions there report on this task."""
    found = repo.find(path)
    subprocess.run(["git", "config", "teamloop.task", task], cwd=found.root, check=True, stdin=subprocess.DEVNULL,
                   capture_output=True)
    event = normalize.event("task_start", "app", {}, {"title": title} if title else {})
    event.update(repo=found.root.name, branch=repo.branch(found), task=task)
    spool.append(redact.redact_obj(event))
    return repo_status(str(found.root))


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

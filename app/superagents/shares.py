"""Super Team → Files, on this laptop.

Sharing: the files are read here, refused if they look like secrets (a .env, a key, or text with a token in it),
uploaded straight to the storage link the hub hands out (never through the hub), then the hub checks they arrived.
Receiving: each file is downloaded through a 5-minute link, checked against the sender's SHA-256 and saved only into a
repo's .superagents/inbox/<share>/, which git never sees (.git/info/exclude). Nothing received is ever run.
A branch handed over is checked out with git, in a repo whose working tree is clean.
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
import subprocess
import urllib.request
from pathlib import Path
from typing import Callable

from teamloop import redact

MAX_BYTES = 25 * 1024 * 1024
SECRET_FILES = re.compile(r"(^|[\\/])(\.env(\.[\w.-]+)?|\.npmrc|\.pypirc|\.netrc|id_(rsa|dsa|ecdsa|ed25519)|[^\\/]+\.(pem|key|p12|pfx|kdbx|keystore))$", re.I)
INBOX = Path(".superagents") / "inbox"
Hub = Callable[..., dict]


def clean_name(name: str) -> str:
    base = re.split(r"[\\/]", str(name))[-1]
    base = re.sub(r"[\x00-\x1f<>:\"|?*]", "_", base).strip(" .")
    if not base:
        raise ValueError(f"{name!r} isn't a file name")
    return base[:120]


def prepare(files: list[tuple[str, bytes]]) -> list[dict]:
    out = []
    for name, data in files:
        if SECRET_FILES.search(name):
            raise PermissionError(re.split(r"[\\/]", name)[-1] + " is a secrets file; it isn't shared")
        if len(data) > MAX_BYTES:
            raise ValueError(f"{clean_name(name)} is over 25 MB")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = None  # binary: there's no text to scan
        if text is not None:
            for n, (a, b) in enumerate(zip(text.splitlines(), redact.redact(text).splitlines()), 1):
                if a != b:
                    raise PermissionError(f"{clean_name(name)} has something that looks like a secret on line {n}; take it out first")
        out.append({"name": clean_name(name), "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "data": data})
    return out


def send(hub: Hub, files: list[tuple[str, bytes]], to: str = "", note: str = "") -> dict:
    prepped = prepare(files)
    if not prepped:
        raise ValueError("Pick a file to share")
    share = hub("POST", "shares", {"to": to or None, "note": note, "files": [{k: f[k] for k in ("name", "size", "sha256")} for f in prepped]})
    for f, up in zip(prepped, share["uploads"]):
        req = urllib.request.Request(up["url"], data=f["data"], method=up.get("method", "PUT"),
                                     headers={**(up.get("headers") or {}),
                                              "Content-Type": mimetypes.guess_type(f["name"])[0] or "application/octet-stream"})
        with urllib.request.urlopen(req, timeout=300) as r:
            r.read()
    return hub("POST", f"shares/{share['id']}/ready")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)


def _exclude(root: Path) -> None:
    """Saved files stay out of commits: .superagents/inbox/ goes in the repo's own exclude list (not .gitignore)."""
    where = _git(root, "rev-parse", "--git-path", "info/exclude").stdout.strip()
    if not where:
        return
    f = Path(where) if Path(where).is_absolute() else root / where
    have = f.read_text(encoding="utf-8") if f.exists() else ""
    if "/.superagents/inbox/" not in have.splitlines():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(have + ("" if not have or have.endswith("\n") else "\n") + "/.superagents/inbox/\n", encoding="utf-8")


def _free(p: Path) -> Path:
    n = 2
    while p.exists():
        p = p.with_name(f"{p.stem.rsplit(' (', 1)[0]} ({n}){p.suffix}")
        n += 1
    return p


def save(hub: Hub, share: dict, root: Path) -> list[Path]:
    if share["kind"] != "files" or share["status"] != "ready":
        raise ValueError("That share has no files to save" if share["kind"] != "files" else f"That share is {share['status']}")
    folder = root / INBOX / share["id"][:8]
    folder.mkdir(parents=True, exist_ok=True)
    _exclude(root)
    saved = []
    for f in share["files"]:
        got = hub("GET", f"shares/{share['id']}/files/{f['n']}")
        with urllib.request.urlopen(got["url"], timeout=300) as r:
            data = r.read(MAX_BYTES + 1)
        if len(data) != got["size"] or hashlib.sha256(data).hexdigest() != got["sha256"]:
            raise RuntimeError(f"{got['name']} didn't arrive intact; try again")
        target = _free(folder / clean_name(got["name"]))
        target.write_bytes(data)
        saved.append(target)
    return saved


def checkout(root: Path, branch: str) -> str:
    """A branch a teammate handed over, in this repo: fetched and switched to, only if nothing here is uncommitted."""
    if not re.fullmatch(r"[A-Za-z0-9._/-]{1,200}", branch or "") or ".." in branch:
        raise ValueError("That isn't a branch name")
    if _git(root, "status", "--porcelain", "--untracked-files=no").stdout.strip():
        raise RuntimeError(f"{root.name} has uncommitted changes: commit or stash them first")
    fetched = _git(root, "fetch", "origin", branch)
    if fetched.returncode != 0:
        raise RuntimeError((fetched.stderr or "git fetch failed").strip()[:500])
    r = _git(root, "switch", branch) if _git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0 \
        else _git(root, "switch", "--track", f"origin/{branch}")
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "git switch failed").strip()[:500])
    if _git(root, "rev-parse", "--abbrev-ref", "@{u}").returncode == 0:
        _git(root, "merge", "--ff-only", "@{u}")
    return branch

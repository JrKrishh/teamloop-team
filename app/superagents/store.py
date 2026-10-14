"""The app's own state, next to the connector's: ~/.teamloop/app.json (the hub session, who you are, the team you
picked) and ~/.teamloop/repos.json (the repos you connected from the app)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from teamloop import spool


def _path(name: str) -> Path:
    return spool.home() / name


def _read(name: str, default):
    try:
        return json.loads(_path(name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(name: str, data) -> None:
    path = _path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def load() -> dict:
    return _read("app.json", {})


def save(state: dict) -> None:
    _write("app.json", state)


def clear() -> None:
    _path("app.json").unlink(missing_ok=True)


def remote() -> dict:
    """Remote control from a phone: on or off, and the paired phones with their keys (this file is 0600)."""
    d = _read("remote.json", {})
    return {"on": bool(d.get("on")), "phones": [p for p in d.get("phones", []) if isinstance(p, dict) and p.get("id")]}


def save_remote(d: dict) -> None:
    _write("remote.json", d)


def repos() -> list[str]:
    return [r for r in _read("repos.json", []) if isinstance(r, str)]


def add_repo(path: str) -> None:
    have = repos()
    if path not in have:
        _write("repos.json", have + [path])

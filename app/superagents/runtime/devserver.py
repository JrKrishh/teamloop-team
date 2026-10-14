"""Dev servers for the agent browser, like Claude Code's preview: a repo's dev command from .superagents/launch.json
(or the dev/start script in package.json) runs in the background, the agent waits for its port, then opens it.

launch.json: {"configurations": [{"name": "web", "command": "npm run dev", "port": 5173}]}  (url optional)
Output goes to ~/.teamloop/devservers/<repo>-<name>.log; servers stop with the app."""

from __future__ import annotations

import atexit
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

from teamloop import spool

SERVERS: dict[str, dict] = {}
URL = re.compile(r"https?://(?:localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0):(\d{2,5})")


def configs(root: Path) -> list[dict]:
    f = root / ".superagents" / "launch.json"
    if f.exists():
        data = json.loads(f.read_text(encoding="utf-8"))
        return [c for c in data.get("configurations", []) if isinstance(c, dict) and c.get("name") and c.get("command")]
    pkg = root / "package.json"
    if pkg.exists():
        scripts = (json.loads(pkg.read_text(encoding="utf-8")).get("scripts") or {})
        for name in ("dev", "start"):
            if name in scripts:
                m = re.search(r"(?:--port|-p)[ =](\d{2,5})", scripts[name])
                return [{"name": name, "command": f"npm run {name}", "port": int(m.group(1)) if m else None}]
    return []


def _open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _log(key: str) -> Path:
    d = spool.home() / "devservers"
    d.mkdir(parents=True, exist_ok=True)
    return d / (re.sub(r"[^A-Za-z0-9_.-]", "-", key) + ".log")


def tail(key: str, n: int = 40) -> str:
    try:
        return "\n".join(_log(key).read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
    except OSError:
        return ""


def _stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        if sys.platform == "win32":  # the shell, npm and node under it
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        else:
            proc.terminate()


def start(root: Path, name: str = "", wait: float = 90) -> dict:
    cfgs = configs(root)
    if not cfgs:
        raise ValueError(f"{root.name} has no dev server to start: add .superagents/launch.json, or a dev or start script")
    cfg = next((c for c in cfgs if c["name"] == name), None) if name else cfgs[0]
    if not cfg:
        raise ValueError(f"No dev server named {name}; {root.name} has {', '.join(c['name'] for c in cfgs)}")
    key = f"{root.name}-{cfg['name']}"
    have = SERVERS.get(key)
    if have and have["proc"].poll() is None:
        return {**have, "already": True}
    port = cfg.get("port")
    if port and _open(int(port)):
        url = cfg.get("url") or f"http://localhost:{port}"
        return {"key": key, "url": url, "already": True, "command": cfg["command"], "proc": None}
    log = _log(key)
    out = open(log, "w", encoding="utf-8")  # noqa: SIM115 - the server writes to it until it stops
    proc = subprocess.Popen(cfg["command"], shell=True, cwd=root, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            env={**os.environ, "BROWSER": "none", "FORCE_COLOR": "0"},
                            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0)
    end, url = time.time() + wait, None
    while time.time() < end:
        if proc.poll() is not None:
            raise RuntimeError(f"`{cfg['command']}` stopped (exit {proc.returncode}):\n{tail(key)}")
        if port and _open(int(port)):
            url = cfg.get("url") or f"http://localhost:{port}"
            break
        m = None if port else URL.search(tail(key, 200))
        if m and _open(int(m.group(1))):
            url = cfg.get("url") or f"http://localhost:{m.group(1)}"
            break
        time.sleep(0.4)
    if not url:
        _stop(proc)
        raise RuntimeError(f"`{cfg['command']}` didn't open a port within {int(wait)} s:\n{tail(key)}")
    SERVERS[key] = {"key": key, "url": url, "command": cfg["command"], "proc": proc}
    return {**SERVERS[key], "already": False}


def stop(root: Path, name: str = "") -> list[str]:
    gone = []
    for key, s in list(SERVERS.items()):
        if key.startswith(f"{root.name}-") and (not name or key == f"{root.name}-{name}"):
            _stop(s["proc"])
            SERVERS.pop(key)
            gone.append(key)
    return gone


@atexit.register
def _stop_all() -> None:
    for s in SERVERS.values():
        _stop(s["proc"])

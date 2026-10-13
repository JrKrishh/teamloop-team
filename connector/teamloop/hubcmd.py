"""`teamloop hub`: run your team's hub and board on this machine.

First run creates the room, a room token (teammates use it through their invite) and a lead key (you sign in to
the board with it). They are kept in ~/.teamloop/hub/settings.json, and the data in ~/.teamloop/hub/hub.db,
so a restart keeps everything. Teammates elsewhere reach it through a tunnel, e.g.
`cloudflared tunnel --url http://localhost:8799`, then `teamloop hub --public-url <that URL>` prints their invite.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import sys
import webbrowser

from teamloop import login, spool


def _settings(room: str) -> dict:
    path = spool.home() / "hub" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if cfg.get("room") != room:
        cfg = {"room": room, "room_token": secrets.token_urlsafe(18), "lead_key": secrets.token_urlsafe(18),
               "secret": secrets.token_urlsafe(32)}
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return cfg


def _lan_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packet is sent; this only picks the outbound interface
            return s.getsockname()[0]
    except OSError:
        return None


def run(port: int = 8799, host: str = "127.0.0.1", room: str = "teamloop", public_url: str | None = None,
        open_browser: bool = True, demo: bool = False) -> int:
    try:
        import uvicorn
        from hub.app import app_from_env
    except ImportError:
        print("This install of teamloop doesn't include the hub. Use teamloop.exe, or `pip install -e hub` from the repo.")
        return 2
    if not login.ROOM_RE.match(room):
        print("Room names use 3-64 letters, digits, _ . or -")
        return 2
    cfg = _settings(room)
    base = spool.home() / "hub"
    os.environ.setdefault("HUB_DB", str(base / "hub.db"))
    os.environ.setdefault("HUB_SECRET", cfg["secret"])
    os.environ.setdefault("HUB_SECURE_COOKIE", "0" if not (public_url or "").startswith("https://") else "1")
    os.environ["CCBRIDGE_ROOMS"] = f"{room}:{cfg['room_token']}"
    os.environ["CCBRIDGE_OPEN_ROOMS"] = "0"
    os.environ["HUB_LEAD_KEYS"] = f"{room}:{cfg['lead_key']}"
    if demo:
        os.environ["HUB_DEMO_ROOM"] = "demo"

    sys.stdout.reconfigure(line_buffering=True)  # the hub then runs for hours: don't leave these lines in a buffer
    local = f"http://localhost:{port}"
    reach = (public_url or "").rstrip("/") or (f"http://{_lan_ip()}:{port}" if host == "0.0.0.0" and _lan_ip() else local)
    print(f"TeamLoop hub  room '{room}'  data {base}")
    print(f"  Board:      {local}   (sign in: room '{room}', lead key below)")
    print(f"  Lead key:   {cfg['lead_key']}   (keep it to yourself; also in {base / 'settings.json'})")
    print(f"  Invite for teammates (reach the hub at {reach}):")
    print(f"    teamloop login {login.invite(reach, room, cfg['room_token'])} --name <their name>")
    if reach == local:
        print("  Teammates on other machines need a reachable URL: run `cloudflared tunnel --url "
              f"{local}` and restart with --public-url <that https URL>, or use --host 0.0.0.0 on a LAN.")
    if not os.environ.get("NEBIUS_API_KEY"):
        print("  NEBIUS_API_KEY is not set: the board works, but Agent S can't estimate, answer or write digests.")
    if open_browser:
        webbrowser.open(local)
    uvicorn.run(app_from_env(), host=host, port=port, log_level="warning")
    return 0

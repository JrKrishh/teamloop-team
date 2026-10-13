"""`teamloop login`: with no invite, sign in to the cloud hub (device flow, docs/cloud.md). With an invite, join a
self-hosted hub: `teamloop invite` (lead) makes those in ccbridge's format, base64url of {"u": hub url, "r": room,
"t": room token}, so a ccbridge invite works here too."""

from __future__ import annotations

import base64
import binascii
import getpass
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from teamloop import spool

NAME_RE = re.compile(r"^[A-Za-z0-9 _.\-]{1,64}$")  # ccbridge's display-name rule
ROOM_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,64}$")


def encode(url: str, room: str, token: str) -> str:
    blob = json.dumps({"u": url, "r": room, "t": token}, separators=(",", ":"))
    return base64.urlsafe_b64encode(blob.encode()).decode().rstrip("=")


def decode(invite: str) -> tuple[str, str, str]:
    invite = invite.strip()
    try:
        data = json.loads(base64.urlsafe_b64decode(invite + "=" * (-len(invite) % 4)))
        url, room, token = data["u"], data["r"], data["t"]
    except (binascii.Error, ValueError, KeyError, TypeError):
        raise ValueError("that invite is not valid; copy the whole invite again") from None
    if not (isinstance(url, str) and url.startswith(("http://", "https://")) and isinstance(room, str)
            and ROOM_RE.match(room) and isinstance(token, str) and token):
        raise ValueError("that invite is not valid; copy the whole invite again")
    return url.rstrip("/"), room, token


def default_name() -> str:
    name = re.sub(r"[^A-Za-z0-9 _.\-]", "", getpass.getuser())[:64]
    return name or "dev"


def join(cfg: dict) -> str:
    """POST /v1/join; returns the session id. Raises urllib.error.HTTPError on refusal."""
    body = {"room": cfg["room"], "display_name": cfg["name"], "identity_key": cfg["identity_key"]}
    req = urllib.request.Request(cfg["url"] + "/v1/join", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "Authorization": f"Bearer {cfg['token']}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())["session_id"]


_session: dict[str, str] = {}


def request(cfg: dict, method: str, path: str, body: dict | None = None) -> dict:
    """A hub call. Cloud hub: the connector token from `teamloop login`. Self-hosted hub: ccbridge auth, room
    token + the session from /v1/join; a 401 there means the session expired or the hub restarted, so join again
    once and retry."""
    if cfg.get("mode") == "cloud":
        req = urllib.request.Request(cfg["url"] + path, json.dumps(body).encode() if body is not None else None, {
            "Content-Type": "application/json", "Authorization": f"Bearer {cfg['token']}"}, method=method)
        with urllib.request.urlopen(req, timeout=60) as r:  # a board read may wait on Agent S
            raw = r.read()
            return json.loads(raw) if raw else {}
    for attempt in (1, 2):
        if "id" not in _session:
            _session["id"] = join(cfg)
        req = urllib.request.Request(cfg["url"] + path, json.dumps(body).encode() if body is not None else None, {
            "Content-Type": "application/json", "Authorization": f"Bearer {cfg['token']}",
            "X-CCBridge-Room": cfg["room"], "X-CCBridge-Session": _session["id"]}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            if e.code == 401 and attempt == 1:
                _session.pop("id", None)
                continue
            raise
    return {}


def save(cfg: dict) -> None:
    path = spool.home() / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def login(invite: str, name: str | None = None) -> int:
    try:
        url, room, token = decode(invite)
    except ValueError as e:
        print(e)
        return 2
    name = name or default_name()
    if not NAME_RE.match(name):
        print("names may use letters, digits, spaces, _ . and - (max 64)")
        return 2
    old = {}
    try:
        old = json.loads((spool.home() / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    same = old.get("url") == url and old.get("room") == room and old.get("name") == name
    cfg = {"url": url, "room": room, "token": token, "name": name,
           "identity_key": old["identity_key"] if same and old.get("identity_key") else secrets.token_urlsafe(32)}
    try:
        join(cfg)
    except urllib.error.HTTPError as e:
        why = {403: "the hub refused the invite (wrong room or token)",
               409: f"'{name}' is already taken in this room by someone else; use --name"}.get(e.code, f"hub said {e.code}")
        print(f"Couldn't join: {why}")
        return 1
    except OSError as e:
        print(f"Couldn't reach the hub at {url}: {e}")
        return 1
    save(cfg)
    print(f"Joined {room} as {name}. Your sessions' summaries and facts now go to {url}.")
    return 0


def _call(url: str, method: str = "GET", body: dict | None = None) -> dict:
    req = urllib.request.Request(url, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def device_login(hub: str, open_url=None, sleep=time.sleep) -> int:
    """`teamloop login` without an invite: sign in on the cloud hub in a browser window, like `gh auth login`.
    The CLI shows a code, the person approves it on the web (Google or email sign-in), the CLI gets a token once."""
    from teamloop import window

    open_url = open_url or window.open_app
    hub = hub.rstrip("/")
    try:
        start = _call(hub + "/v1/device/start", "POST", {"label": default_name()})
    except (OSError, ValueError) as e:
        print(f"Couldn't reach TeamLoop at {hub}: {e}")
        return 1
    print(f"Your code: {start['user_code']}")
    print(f"Approve it in the window that opens (sign in with Google or email): {start['verify_url']}")
    open_url(start["verify_url"])
    deadline = time.time() + start.get("expires_in", 900)
    while time.time() < deadline:
        sleep(start.get("interval", 3))
        try:
            got = _call(hub + "/v1/device/poll?" + urllib.parse.urlencode({"device_code": start["device_code"]}))
        except (OSError, ValueError):
            continue  # a blip; keep waiting
        if got["status"] == "approved":
            save({"mode": "cloud", "url": got["url"].rstrip("/"), "token": got["token"], "name": got["name"], "team": got["team"]})
            print(f"Connected to {got['team']['name']} as {got['name']}. Next, in your repo: teamloop init")
            return 0
        if got["status"] != "pending":
            break
    print("That code expired before it was approved. Run `teamloop login` again.")
    return 1


def invite(url: str, room: str, token: str | None = None) -> str:
    return encode(url.rstrip("/"), room, token or secrets.token_urlsafe(24))

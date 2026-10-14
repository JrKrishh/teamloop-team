"""Remote control from your phone, like Claude Code's Remote Control: the turns run on this laptop; the phone sees
your chats, sends messages, watches a turn live (also one started at the desk), approves or denies its steps, runs a
plan and stops a turn.

Pairing is a QR code in Settings. It carries a channel id and a 256-bit key in the URL's fragment, which browsers never
send to a server. Every message is sealed with AES-256-GCM under that key, with the channel id bound in, so the relay in
between (Supabase Realtime in production, the hub's own socket in development) carries only noise. Messages older than
two minutes, or seen before, are dropped; a phone's message is never taken for the laptop's or the other way round. The
phone can do only what the chat window does, through the same local API. Unpair deletes the key."""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from websockets.sync.client import connect

from . import store

FRESH = 120  # seconds a message stays valid
PAIR_TTL = 600  # a pairing code nobody scanned expires
TURN_ID = re.compile(r"[A-Za-z0-9_-]{4,64}")


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def seal(key: bytes, channel: str, msg: dict) -> dict:
    iv = os.urandom(12)
    return {"iv": b64(iv), "c": b64(AESGCM(key).encrypt(iv, json.dumps(msg).encode(), channel.encode()))}


def unseal(key: bytes, channel: str, env: dict) -> dict:
    return json.loads(AESGCM(key).decrypt(unb64(env["iv"]), unb64(env["c"]), channel.encode()))


def relay_url(hub: str, cfg: dict) -> Optional[str]:
    """Where phone and laptop meet: Supabase Realtime when the hub has it, else the hub's own socket (not on Vercel)."""
    if cfg.get("relay") == "supabase":
        base = cfg["supabase_url"].rstrip("/").replace("https://", "wss://", 1)
        return f"{base}/realtime/v1/websocket?apikey={urllib.parse.quote(cfg['supabase_key'])}&vsn=1.0.0"
    if cfg.get("relay") == "hub":
        return hub.rstrip("/").replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/v1/relay?vsn=1.0.0"
    return None


class Relay:
    """One channel on a Phoenix-protocol socket (what Supabase Realtime speaks; the hub's dev relay speaks the same)."""

    def __init__(self, url: str, topic: str, on_message: Callable[[dict], None]) -> None:
        self.url, self.topic, self.on_message = url, topic, on_message
        self.ws, self.ref, self.stopped, self.joined = None, 0, False, threading.Event()
        self.lock = threading.Lock()

    def start(self) -> "Relay":
        threading.Thread(target=self._run, daemon=True, name=f"relay {self.topic[-8:]}").start()
        return self

    def _send(self, event: str, payload: dict, topic: Optional[str] = None) -> None:
        with self.lock:
            self.ref += 1
            if self.ws is None:
                raise ConnectionError("not connected")
            self.ws.send(json.dumps({"topic": topic or self.topic, "event": event, "payload": payload, "ref": str(self.ref)}))

    def broadcast(self, env: dict) -> bool:
        try:
            self._send("broadcast", {"type": "broadcast", "event": "m", "payload": env})
            return True
        except Exception:  # noqa: BLE001 - offline for a moment; the phone asks again
            return False

    def _run(self) -> None:
        wait = 1.0
        while not self.stopped:
            try:
                with connect(self.url, open_timeout=10, close_timeout=2, max_size=2 ** 21) as ws:
                    self.ws = ws
                    self._send("phx_join", {"config": {"broadcast": {"self": False, "ack": False}, "presence": {"key": ""},
                                                       "private": False}})
                    wait, beat = 1.0, time.time()
                    while not self.stopped:
                        if time.time() - beat > 25:
                            self._send("heartbeat", {}, "phoenix")
                            beat = time.time()
                        try:
                            m = json.loads(ws.recv(timeout=5))
                        except TimeoutError:
                            continue
                        if m.get("event") == "phx_reply" and m.get("topic") == self.topic:
                            self.joined.set()
                        elif m.get("event") == "broadcast" and m.get("topic") == self.topic:
                            env = (m.get("payload") or {}).get("payload")
                            if isinstance(env, dict):
                                try:
                                    self.on_message(env)
                                except Exception:  # noqa: BLE001 - one bad message never drops the line
                                    pass
            except Exception:  # noqa: BLE001 - the network or the relay went away: try again, slower each time
                pass
            self.ws = None
            self.joined.clear()
            if not self.stopped:
                time.sleep(wait)
                wait = min(wait * 2, 30.0)

    def stop(self) -> None:
        self.stopped = True
        ws = self.ws
        if ws is not None:
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass


def pair(hub: str) -> dict:
    """A new phone: a channel id and a key, shown once as a QR code. Codes nobody scanned go after ten minutes."""
    cfg, now = store.remote(), time.time()
    phones = [p for p in cfg["phones"] if p.get("paired") or now - p.get("created", 0) < PAIR_TTL]
    p = {"id": secrets.token_hex(16), "key": b64(AESGCM.generate_key(256)), "name": "", "created": now, "paired": None}
    store.save_remote({**cfg, "on": True, "phones": phones + [p]})
    return {"id": p["id"], "url": f"{hub.rstrip('/')}/remote/#p={p['id']}&k={p['key']}"}


def unpair(pid: str) -> None:
    cfg = store.remote()
    store.save_remote({**cfg, "phones": [p for p in cfg["phones"] if p["id"] != pid]})


def status(online: dict[str, float], ready: bool = False) -> dict:
    """For Settings: on or off, whether a relay is there, and the paired phones (online: heard from in 90 s)."""
    cfg, now = store.remote(), time.time()
    return {"on": cfg["on"], "ready": ready, "phones": [
        {"id": p["id"], "name": p.get("name") or "A phone", "paired": p.get("paired"), "online": now - online.get(p["id"], 0) < 90}
        for p in cfg["phones"] if p.get("paired")]}


def slim(e: dict) -> dict:
    """A turn event for a phone screen: long tool output and file contents are cut (the laptop keeps them whole)."""
    e = dict(e)
    if isinstance(e.get("result"), str) and len(e["result"]) > 1500:
        e["result"] = e["result"][:1500] + "\n…"
    if isinstance(e.get("args"), dict):
        e["args"] = {k: v[:4000] + "…" if isinstance(v, str) and len(v) > 4000 else v for k, v in e["args"].items()}
    return e


class Remote:
    """Connects a relay per paired phone while remote control is on, and answers each phone through the local API."""

    def __init__(self, api: Callable[..., dict], relay: Callable[[], Optional[str]], team: Callable[[], Optional[str]],
                 relay_cls: type = Relay) -> None:
        self.api, self.relay, self.team, self.relay_cls = api, relay, team, relay_cls
        self.relays: dict[str, Relay] = {}
        self.seen: dict[str, float] = {}  # message ids, so a replayed message does nothing
        self.followed: set[tuple[str, str]] = set()  # (phone, turn) being streamed
        self.online: dict[str, float] = {}  # phone id -> last message
        self.lock = threading.Lock()

    def start(self, every: float = 5.0) -> None:
        def loop() -> None:
            while True:
                try:
                    self.sync()
                except Exception:  # noqa: BLE001 - not signed in yet, or the hub is away
                    pass
                time.sleep(every)
        threading.Thread(target=loop, daemon=True, name="remote").start()

    def sync(self) -> None:
        cfg = store.remote()
        want = {p["id"]: p for p in cfg["phones"]} if cfg["on"] else {}
        url = self.relay() if want else None
        for pid in list(self.relays):
            if pid not in want or not url:
                self.relays.pop(pid).stop()
        for pid, p in want.items():
            if pid not in self.relays and url:
                key = unb64(p["key"])
                self.relays[pid] = self.relay_cls(url, f"realtime:sa-{pid}",
                                                  lambda env, pid=pid, key=key: self.receive(pid, key, env)).start()

    def status(self) -> dict:
        try:
            ready = bool(self.relay())
        except Exception:  # noqa: BLE001 - the hub is away
            ready = False
        return status(self.online, ready)

    def receive(self, pid: str, key: bytes, env: dict) -> None:
        try:
            msg = unseal(key, pid, env)
        except Exception:  # noqa: BLE001 - not sealed with this phone's key: noise, or someone guessing
            return
        now, ts = time.time(), msg.get("ts")
        if (msg.get("from") != "phone" or not isinstance(msg.get("id"), str) or not isinstance(ts, (int, float))
                or abs(now - ts / 1000) > FRESH):
            return
        with self.lock:
            if msg["id"] in self.seen:
                return
            self.seen = {k: t for k, t in self.seen.items() if now - t < 2 * FRESH}
            self.seen[msg["id"]] = now
            self.online[pid] = now
        if msg.get("t") == "hello":
            self._paired(pid, str(msg.get("device") or "")[:60])
        threading.Thread(target=self.handle, args=(pid, key, msg), daemon=True).start()

    def _paired(self, pid: str, device: str) -> None:
        cfg = store.remote()
        for p in cfg["phones"]:
            if p["id"] == pid and (not p.get("paired") or (device and p.get("name") != device)):
                p["paired"], p["name"] = p.get("paired") or time.time(), device or p.get("name") or ""
                store.save_remote(cfg)

    def send(self, pid: str, key: bytes, msg: dict) -> bool:
        r = self.relays.get(pid)
        return r is not None and r.broadcast(seal(key, pid, {**msg, "from": "laptop", "id": secrets.token_hex(8),
                                                            "ts": int(time.time() * 1000)}))

    def handle(self, pid: str, key: bytes, msg: dict) -> None:
        t = msg.get("t")
        try:
            turn = str(msg.get("turn") or "")
            if t in ("watch", "decide", "stop", "run_plan") and not TURN_ID.fullmatch(turn):
                raise ValueError("That turn isn't on this laptop")
            if t == "hello":
                out = {"t": "state", **self.state()}
            elif t == "ping":  # the phone keeps "online" fresh while it's open
                out = {"t": "pong"}
            elif t == "chat":
                out = {"t": "chat", "chat": self.chat(str(msg.get("chat") or ""))}
            elif t == "send":
                team = self.team()
                if not team:
                    raise ValueError("Sign in to Super Agents on the laptop first.")
                r = self.api("POST", "/api/turns", {"chat": msg.get("chat") or None, "agent": msg.get("agent") or "agent-s",
                                                    "message": str(msg.get("message") or ""), "mode": msg.get("mode") or "manual",
                                                    "model": msg.get("model") or "auto", "team": team})
                self.follow(pid, key, r["turn"], 0)
                out = {"t": "turn", **r}
            elif t == "watch":
                self.follow(pid, key, turn, int(msg.get("after") or 0))
                out = {"t": "ok"}
            elif t == "decide":
                self.api("POST", f"/api/turns/{turn}/decide", {"call": str(msg.get("call") or ""), "approve": bool(msg.get("approve"))})
                out = {"t": "ok"}
            elif t == "stop":
                self.api("POST", f"/api/turns/{turn}/cancel")
                out = {"t": "ok"}
            elif t == "run_plan":
                r = self.api("POST", f"/api/turns/{turn}/run-plan")
                self.follow(pid, key, turn, r["after"])
                out = {"t": "ok"}
            else:
                out = {"t": "error", "error": "That isn't something the phone can do."}
        except Exception as e:  # noqa: BLE001 - shown on the phone
            out = {"t": "error", "error": str(e)[:300] or type(e).__name__}
        self.send(pid, key, {**out, "re": msg.get("id")})

    def state(self) -> dict:
        boot = self.api("GET", "/api/boot")
        return {"laptop": socket.gethostname(), "user": (boot.get("user") or {}).get("name"), "signed_in": boot.get("signed_in"),
                "agents": [{k: a.get(k) for k in ("id", "name", "color", "mode")} for a in self.api("GET", "/api/agents")["agents"]],
                "chats": self.api("GET", "/api/chats")["chats"][:40], "live": self.api("GET", "/api/turns")["turns"]}

    def chat(self, cid: str) -> dict:
        c = self.api("GET", f"/api/chats/{urllib.parse.quote(cid)}")
        view = (c.get("view") or [])[-15:]
        return {**c, "view": [{**v, "events": [slim(e) for e in v.get("events") or []]} for v in view]}

    def follow(self, pid: str, key: bytes, turn: str, after: int) -> None:
        """Stream a turn's events to the phone until it ends (one stream per phone and turn). Asked again while it
        streams, as a phone does after it lost the line, it sends what came after `after` once; the phone drops what
        it already has."""
        with self.lock:
            again = (pid, turn) in self.followed
            self.followed.add((pid, turn))

        def catch_up() -> None:
            try:
                evs = self.api("GET", f"/api/turns/{turn}?after={after}").get("events") or []
                for i in range(0, len(evs), 10):
                    self.send(pid, key, {"t": "events", "turn": turn, "events": [slim(e) for e in evs[i:i + 10]]})
            except Exception:  # noqa: BLE001 - the turn is gone
                pass

        def run() -> None:
            n = after
            try:
                while pid in self.relays:
                    r = self.api("GET", f"/api/turns/{turn}?after={n}")  # waits up to 20 s for something new
                    evs = r.get("events") or []
                    if not all(self.send(pid, key, {"t": "events", "turn": turn, "events": [slim(e) for e in evs[i:i + 10]]})
                               for i in range(0, len(evs), 10)):
                        time.sleep(1)  # the line is down for a moment: send these again, never skip them
                        continue
                    if evs:
                        n = evs[-1]["i"] + 1
                    if any(e.get("kind") == "end" for e in evs) or (r.get("done") and not evs):
                        return
            except Exception:  # noqa: BLE001 - the turn is gone; the phone can watch again
                pass
            finally:
                with self.lock:
                    self.followed.discard((pid, turn))
        threading.Thread(target=catch_up if again else run, daemon=True, name=f"follow {turn[:8]}").start()


def local_api(port: int, key: str) -> Callable[..., dict]:
    """The app's own API, the way the chat window calls it."""
    def call(method: str, path: str, body: Optional[dict] = None) -> dict:
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"X-App-Key": key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read()).get("detail")
            except ValueError:
                detail = None
            raise RuntimeError(detail if isinstance(detail, str) else f"The app said {e.code}") from None
    return call

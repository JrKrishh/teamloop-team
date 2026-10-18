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
APPROVAL_ID = re.compile(r"[0-9a-f-]{36}")
TASK_ID = re.compile(r"[A-Za-z0-9_.-]{1,40}")


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
        {"id": p["id"], "name": p.get("name") or "A phone", "paired": p.get("paired"), "online": now - online.get(p["id"], 0) < 90,
         "account": p.get("account")}
        for p in cfg["phones"] if p.get("paired")]}


def slim(e: dict) -> dict:
    """A turn event for a phone screen: long tool output and file contents are cut (the laptop keeps them whole)."""
    e = dict(e)
    if isinstance(e.get("result"), str) and len(e["result"]) > 1500:
        e["result"] = e["result"][:1500] + "\n…"
    if isinstance(e.get("args"), dict):
        e["args"] = {k: v[:4000] + "…" if isinstance(v, str) and len(v) > 4000 else v for k, v in e["args"].items()}
    return e


def slim_live(turns: list) -> list:
    """Running turns for a phone, with the question each waits on (or its step), arguments cut like events."""
    cut = lambda s: s and {**s, "args": slim({"args": s.get("args") or {}})["args"]}  # noqa: E731
    return [{**t, "ask": cut(t.get("ask")), "now": cut(t.get("now"))} for t in turns]


def board_view(b: dict) -> dict:
    """The team board for a phone: each task's status, Agent S's estimate next to the coding agent's claim, who,
    when, and what blocks it, is happening or comes next."""
    def texts(items, n):
        return [x.get("text") for x in (items or [])[:n] if isinstance(x, dict)]
    tasks = []
    for t in (b.get("tasks") or [])[:60]:
        p, pr = t.get("progress") or {}, t.get("pr") or None
        tasks.append({"task": t.get("task"), "title": t.get("title") or "", "status": t.get("status"), "owner": t.get("owner"),
                      "members": t.get("members") or [], "tools": t.get("tools") or [], "due": t.get("due"),
                      "percent": p.get("percent"), "says": p.get("agent_says_percent"), "confidence": p.get("confidence"),
                      "blockers": texts(p.get("blockers"), 3), "doing": texts(p.get("doing"), 1), "next": texts(p.get("next"), 2),
                      "pr": pr and {k: pr.get(k) for k in ("number", "state", "draft", "checks")}, "last": t.get("last_activity"),
                      "editing": [e.get("file") for e in (t.get("editing") or [])[:3]]})
    overlaps = [{"file": f"{o.get('repo')}/{o.get('file')}", "who": [w.get("member") for w in o.get("who") or []]}
                for o in (b.get("overlaps") or [])[:5]]  # two sessions in one file: where merge conflicts start
    return {"room": b.get("room"), "tasks": tasks, "overlaps": overlaps}


def notes_view(got: dict, me: Optional[str]) -> list:
    """A task's notes between the people and agents on it, oldest first, for a phone: `to` is a name, "you", or None for
    everyone."""
    def to(m: dict) -> Optional[str]:
        return None if not m.get("to") else "you" if m["to"]["id"] == me else m["to"]["name"]
    return [{"from": m["from"]["name"], "mine": m["from"]["id"] == me, "agent": m["via"] == "agent", "to": to(m),
             "text": m["text"], "at": m["at"]} for m in reversed(got.get("messages") or [])][-30:]


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
        threading.Thread(target=self.push_live, daemon=True, name="remote live").start()

    def push_live(self, every: float = 2.0, rounds: Optional[int] = None, asks_every: float = 6.0) -> None:
        """While a phone is open, tell it when running turns change, so a question from a turn started at the desk
        reaches its Needs you list in seconds; for a lead, also the steps of members' agents waiting on their yes."""
        last, asks, asks_at = None, [], 0.0
        while rounds is None or rounds > 0:
            rounds = None if rounds is None else rounds - 1
            time.sleep(every)
            try:
                now = time.time()
                open_ = [pid for pid, t in list(self.online.items()) if now - t < 90 and pid in self.relays]
                if not open_:
                    last = None
                    continue
                if now - asks_at >= asks_every:  # the hub, less often than this laptop's own turns
                    asks, asks_at = self.team_asks(), now
                live = {"live": slim_live(self.api("GET", "/api/turns")["turns"]), "asks": asks}
                if live == last:
                    continue
                last = live
                keys = {p["id"]: unb64(p["key"]) for p in store.remote()["phones"]}
                for pid in open_:
                    if pid in keys:
                        self.send(pid, keys[pid], {"t": "live", **live})
            except Exception:  # noqa: BLE001 - the app is busy or closing; next round
                pass

    def team_asks(self) -> list:
        """A lead's: steps of members' agents waiting on their yes, by the team's rules (none on an older hub)."""
        team = self.team()
        if not team:
            return []
        try:
            got = self.api("GET", f"/api/cloud/approvals?team={urllib.parse.quote(team)}")["approvals"]
        except Exception:  # noqa: BLE001 - an older hub, or the hub is away
            return []
        return [{"id": a["id"], "from": (a.get("from") or {}).get("name") or "A teammate", "what": a.get("what") or "",
                 "detail": (a.get("detail") or "")[:1500], "rule": a.get("rule")} for a in got]

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
            self._paired(pid, str(msg.get("device") or "")[:60], msg.get("account"))
        threading.Thread(target=self.handle, args=(pid, key, msg), daemon=True).start()

    def _paired(self, pid: str, device: str, account=None) -> None:
        """A phone said hello: it's paired, under its device name, and who it's signed in as (if anyone; shown, not
        trusted: the pairing key is what lets a phone in)."""
        who = {k: str(account.get(k) or "")[:120] for k in ("name", "email")} if isinstance(account, dict) else None
        cfg = store.remote()
        for p in cfg["phones"]:
            if p["id"] == pid and (not p.get("paired") or (device and p.get("name") != device) or p.get("account") != who):
                p["paired"], p["name"], p["account"] = p.get("paired") or time.time(), device or p.get("name") or "", who
                store.save_remote(cfg)

    def send(self, pid: str, key: bytes, msg: dict) -> bool:
        r = self.relays.get(pid)
        return r is not None and r.broadcast(seal(key, pid, {**msg, "from": "laptop", "id": secrets.token_hex(8),
                                                            "ts": int(time.time() * 1000)}))

    def handle(self, pid: str, key: bytes, msg: dict) -> None:
        t = msg.get("t")
        try:
            turn = str(msg.get("turn") or "")
            if t in ("watch", "decide", "stop", "run_plan", "mode", "steer") and not TURN_ID.fullmatch(turn):
                raise ValueError("That turn isn't on this laptop")
            if t == "hello":
                out = {"t": "state", **self.state()}
            elif t == "ping":  # the phone keeps "online" fresh while it's open
                out = {"t": "pong"}
            elif t == "chat":
                out = {"t": "chat", "chat": self.chat(str(msg.get("chat") or ""))}
            elif t == "board":
                team = self.team()
                if not team:
                    raise ValueError("Sign in to Super Agents on the laptop first.")
                out = {"t": "board", **board_view(self.api("GET", f"/api/cloud/board?team={urllib.parse.quote(team)}"))}
            elif t == "send":
                team = self.team()
                if not team:
                    raise ValueError("Sign in to Super Agents on the laptop first.")
                r = self.api("POST", "/api/turns", {"chat": msg.get("chat") or None, "agent": msg.get("agent") or "agent-s",
                                                    "message": str(msg.get("message") or ""), "mode": msg.get("mode") or "manual",
                                                    "model": msg.get("model") or "auto", "effort": msg.get("effort") or "medium",
                                                    "team": team})
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
            elif t == "mode":  # switched on the phone while the answer runs
                self.api("POST", f"/api/turns/{turn}/mode", {"mode": str(msg.get("mode") or "")})
                out = {"t": "ok"}
            elif t == "steer":  # typed on the phone while the answer runs
                self.api("POST", f"/api/turns/{turn}/steer", {"text": str(msg.get("text") or "")[:4000], "via": "phone"})
                out = {"t": "ok"}
            elif t in ("notes", "note"):  # a task's notes; "note" leaves one first, for everyone else on it or one person
                team, task = self.team(), str(msg.get("task") or "")
                if not team or not TASK_ID.fullmatch(task):
                    raise ValueError("That task isn't on your team's board")
                q, skipped = f"team={urllib.parse.quote(team)}", []
                if t == "note":
                    skipped = self.api("POST", f"/api/cloud/messages?{q}", {"to": str(msg.get("to") or "task")[:64],
                                                                           "text": str(msg.get("text") or "")[:1000], "task": task})["skipped"]
                got = self.api("GET", f"/api/cloud/messages?{q}&box=all&task={urllib.parse.quote(task)}")
                out = {"t": "notes", "task": task, "notes": notes_view(got, (self.api("GET", "/api/boot").get("user") or {}).get("id")),
                       "skipped": skipped}
            elif t == "team_decide":  # a lead's yes or no, from the phone, to a step of a member's agent
                aid, team = str(msg.get("approval") or ""), self.team()
                if not APPROVAL_ID.fullmatch(aid) or not team:
                    raise ValueError("That request isn't in your team")
                self.api("POST", f"/api/cloud/approvals/{aid}/decide?team={urllib.parse.quote(team)}", {"approve": bool(msg.get("approve"))})
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
                "agents": [{k: a.get(k) for k in ("id", "name", "color", "mode", "model")} for a in self.api("GET", "/api/agents")["agents"]],
                "prefs": {k: (boot.get("prefs") or {}).get(k) for k in ("model", "effort")},  # what the desktop is set to
                "chats": self.api("GET", "/api/chats")["chats"][:40], "live": slim_live(self.api("GET", "/api/turns")["turns"]),
                "asks": self.team_asks()}

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

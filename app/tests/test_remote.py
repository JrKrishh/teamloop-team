"""Remote control from a phone: the seal, pairing, and the laptop's side of the conversation, with a stand-in relay
and local API. The phone's side (WebCrypto in the browser) is checked against this one in the walkthrough."""

import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from superagents import remote, server, store

TEAM = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("TEAMLOOP_HOME", str(tmp_path / "home"))
    FakeRelay.made.clear()
    return tmp_path


class FakeRelay:
    """Records what the laptop broadcasts; the test plays the phone by calling on_message."""
    made: list = []

    def __init__(self, url, topic, on_message):
        self.url, self.topic, self.on_message, self.sent, self.stopped = url, topic, on_message, [], False
        FakeRelay.made.append(self)

    def start(self):
        return self

    def broadcast(self, env):
        self.sent.append(env)
        return True

    def stop(self):
        self.stopped = True


class Api:
    """Stand-in for the app's local API: one turn that asks before running a command, then answers."""

    def __init__(self):
        self.calls = []
        self.events = [{"i": 0, "kind": "thinking"},
                       {"i": 1, "kind": "tool", "id": "c1", "name": "run_command", "args": {"command": "git status"}, "status": "asking"},
                       {"i": 2, "kind": "answer", "text": "Clean."}, {"i": 3, "kind": "end", "planned": 0}]

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == "/api/boot":
            return {"signed_in": True, "user": {"name": "Yang"}, "prefs": {"theme": "dark", "model": "super", "effort": "high"}}
        if path == "/api/agents":
            return {"agents": [{"id": "agent-s", "name": "Agent S", "color": "#C2554C", "mode": "manual", "model": "auto", "instructions": "private"}]}
        if path == "/api/chats":
            return {"chats": [{"id": "c-1", "title": "Is main clean?", "agent": "agent-s", "updated": 1}]}
        if path == "/api/turns":
            return {"turns": []} if method == "GET" else {"turn": "turn-0001", "chat": "c-2"}
        if path.startswith("/api/turns/turn-0001?after="):
            return {"events": self.events[int(path.split("=")[1]):], "done": True}
        return {"ok": True}


def paired():
    p = remote.pair("https://hub.example")
    return p["id"], remote.unb64(store.remote()["phones"][-1]["key"])


def phone(key, pid, msg, **over):
    body = {"from": "phone", "id": str(time.time_ns()), "ts": int(time.time() * 1000), **msg, **over}
    return remote.seal(key, pid, body)


def heard(relay, key, pid):
    return [remote.unseal(key, pid, env) for env in relay.sent]


def wait_for(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_the_seal_binds_the_key_and_the_channel():
    key = bytes(range(32))
    env = remote.seal(key, "chan", {"t": "hello"})
    assert remote.unseal(key, "chan", env) == {"t": "hello"}
    with pytest.raises(Exception):
        remote.unseal(bytes(32), "chan", env)  # another key
    with pytest.raises(Exception):
        remote.unseal(key, "other", env)  # the same message replayed on another channel
    assert env["iv"] != remote.seal(key, "chan", {"t": "hello"})["iv"]  # a fresh nonce every time


def test_pairing_codes_expire_and_unpair_forgets_the_key(home):
    p = remote.pair("https://hub.example/")
    assert p["url"].startswith(f"https://hub.example/remote/#p={p['id']}&k=")  # the key rides in the fragment
    cfg = store.remote()
    assert cfg["on"] and cfg["phones"][0]["paired"] is None and len(remote.unb64(cfg["phones"][0]["key"])) == 32
    assert remote.status({})["phones"] == []  # not a phone until it says hello
    old = store.remote()
    old["phones"][0]["created"] -= remote.PAIR_TTL + 1
    store.save_remote(old)
    q = remote.pair("https://hub.example")
    assert [x["id"] for x in store.remote()["phones"]] == [q["id"]]  # the code nobody scanned went
    remote.unpair(q["id"])
    assert store.remote()["phones"] == []


def test_where_phone_and_laptop_meet():
    supa = {"relay": "supabase", "supabase_url": "https://ab.supabase.co", "supabase_key": "sb_publishable_x"}
    assert remote.relay_url("https://hub", supa) == "wss://ab.supabase.co/realtime/v1/websocket?apikey=sb_publishable_x&vsn=1.0.0"
    assert remote.relay_url("http://127.0.0.1:8811", {"relay": "hub"}) == "ws://127.0.0.1:8811/v1/relay?vsn=1.0.0"
    assert remote.relay_url("https://hub.example/", {"relay": "hub"}) == "wss://hub.example/v1/relay?vsn=1.0.0"
    assert remote.relay_url("https://hub", {"relay": None}) is None


def test_a_phone_starts_a_turn_watches_it_and_answers_its_question(home):
    pid, key = paired()
    api = Api()
    r = remote.Remote(api, relay=lambda: "wss://relay", team=lambda: TEAM, relay_cls=FakeRelay)
    r.sync()
    relay = FakeRelay.made[0]
    assert relay.topic == f"realtime:sa-{pid}" and relay.url == "wss://relay"
    relay.on_message(phone(key, pid, {"t": "hello", "device": "iPhone · Safari", "account": {"name": "Yang", "email": "yang@example.com"}}, id="m1"))
    assert wait_for(lambda: relay.sent)
    state = heard(relay, key, pid)[0]
    assert state["t"] == "state" and state["re"] == "m1" and state["from"] == "laptop" and state["user"] == "Yang"
    assert state["agents"] == [{"id": "agent-s", "name": "Agent S", "color": "#C2554C", "mode": "manual", "model": "auto"}]  # not its instructions
    assert state["prefs"] == {"model": "super", "effort": "high"}  # the phone starts where the desktop is
    [ph] = remote.status(r.online)["phones"]
    assert ph["id"] == pid and ph["name"] == "iPhone · Safari" and ph["online"] and ph["paired"]
    assert ph["account"] == {"name": "Yang", "email": "yang@example.com"}  # who it's signed in as, shown on the laptop
    relay.on_message(phone(key, pid, {"t": "send", "agent": "agent-s", "mode": "manual", "model": "ultra", "effort": "high", "message": "Is main clean?"}, id="m2"))
    assert wait_for(lambda: any(m.get("re") == "m2" for m in heard(relay, key, pid))  # the reply can come after the events
                    and any(m["t"] == "events" and m["events"][-1]["kind"] == "end" for m in heard(relay, key, pid)))
    got = heard(relay, key, pid)
    started = next(m for m in got if m.get("re") == "m2")
    assert started["t"] == "turn" and started["turn"] == "turn-0001" and started["chat"] == "c-2"
    assert ("POST", "/api/turns", {"chat": None, "agent": "agent-s", "message": "Is main clean?", "mode": "manual", "model": "ultra",
                                   "effort": "high", "team": TEAM}) in api.calls
    assert [e["i"] for m in got if m["t"] == "events" for e in m["events"]] == [0, 1, 2, 3]
    relay.on_message(phone(key, pid, {"t": "decide", "turn": "turn-0001", "call": "c1", "approve": True}, id="m3"))
    assert wait_for(lambda: ("POST", "/api/turns/turn-0001/decide", {"call": "c1", "approve": True}) in api.calls)
    relay.on_message(phone(key, pid, {"t": "mode", "turn": "turn-0001", "mode": "auto"}, id="m5"))  # switched while it ran
    assert wait_for(lambda: ("POST", "/api/turns/turn-0001/mode", {"mode": "auto"}) in api.calls)
    relay.on_message(phone(key, pid, {"t": "steer", "turn": "turn-0001", "text": "Use the Q3 numbers"}, id="m6"))  # typed while it ran
    assert wait_for(lambda: ("POST", "/api/turns/turn-0001/steer", {"text": "Use the Q3 numbers", "via": "phone"}) in api.calls)
    aid = "0f0e0d0c-0b0a-4908-8706-050403020100"  # a lead's yes to a member's agent, from the phone
    relay.on_message(phone(key, pid, {"t": "team_decide", "approval": aid, "approve": True}, id="m7"))
    assert wait_for(lambda: ("POST", f"/api/cloud/approvals/{aid}/decide?team={TEAM}", {"approve": True}) in api.calls)
    relay.on_message(phone(key, pid, {"t": "stop", "turn": "turn-0001"}, id="m4"))
    assert wait_for(lambda: ("POST", "/api/turns/turn-0001/cancel", None) in api.calls)


def test_events_the_line_dropped_are_sent_again_in_order(home):
    pid, key = paired()
    r = remote.Remote(Api(), relay=lambda: "wss://relay", team=lambda: TEAM, relay_cls=FakeRelay)
    r.sync()
    relay = FakeRelay.made[0]
    down, real = iter([False, False]), relay.broadcast
    relay.broadcast = lambda env: next(down, None) is None and real(env)  # the first two sends find the line down
    relay.on_message(phone(key, pid, {"t": "watch", "turn": "turn-0001", "after": 0}))
    assert wait_for(lambda: any(m["t"] == "events" and m["events"][-1]["kind"] == "end" for m in heard(relay, key, pid)), 6)
    assert [e["i"] for m in heard(relay, key, pid) if m["t"] == "events" for e in m["events"]] == [0, 1, 2, 3]


def test_what_the_laptop_ignores_and_what_it_refuses(home):
    pid, key = paired()
    api = Api()
    r = remote.Remote(api, relay=lambda: "wss://relay", team=lambda: None, relay_cls=FakeRelay)
    r.sync()
    relay = FakeRelay.made[0]
    now = int(time.time() * 1000)
    relay.on_message(phone(key, pid, {"t": "hello"}, ts=now - 5 * 60_000))  # too old
    relay.on_message({"iv": "AAAAAAAAAAAAAAAA", "c": "BBBB"})  # noise
    relay.on_message(remote.seal(key, pid, {"from": "laptop", "id": "x", "ts": now, "t": "hello"}))  # the laptop's own words
    relay.on_message(phone(bytes(32), pid, {"t": "hello"}))  # another key
    relay.on_message(phone(key, pid, {"t": "hello"}, ts="soon"))  # no proper time
    time.sleep(0.3)
    assert relay.sent == [] and api.calls == []
    relay.on_message(phone(key, pid, {"t": "hello"}, id="same"))
    relay.on_message(phone(key, pid, {"t": "hello"}, id="same"))  # a replay
    assert wait_for(lambda: len(relay.sent) == 1)
    time.sleep(0.2)
    assert len(relay.sent) == 1
    relay.on_message(phone(key, pid, {"t": "send", "message": "hi"}, id="n1"))  # nobody signed in on the laptop
    relay.on_message(phone(key, pid, {"t": "decide", "turn": "../chats/x", "call": "c", "approve": True}, id="n2"))
    relay.on_message(phone(key, pid, {"t": "read_file", "path": "C:/secrets.txt"}, id="n3"))
    assert wait_for(lambda: len(relay.sent) == 4)
    errors = {m["re"]: m["error"] for m in heard(relay, key, pid) if m["t"] == "error"}
    assert "Sign in" in errors["n1"] and "turn" in errors["n2"] and "phone can" in errors["n3"]
    assert not [c for c in api.calls if c[0] == "POST"]


def test_unpair_and_off_drop_the_line(home):
    pid, key = paired()
    r = remote.Remote(Api(), relay=lambda: "wss://relay", team=lambda: TEAM, relay_cls=FakeRelay)
    r.sync()
    first = FakeRelay.made[0]
    remote.unpair(pid)
    r.sync()
    assert first.stopped and r.relays == {}
    paired()
    r.sync()
    second = FakeRelay.made[-1]
    store.save_remote({**store.remote(), "on": False})
    r.sync()
    assert second.stopped and r.relays == {}


def test_the_phone_gets_the_board_and_whats_waiting(home):
    pid, key = paired()
    api = Api()
    board = {"room": "Loopers", "tasks": [{"task": "T-3", "title": "Fix add()", "status": "in_progress", "owner": "Yang", "members": ["Yang"],
                                            "tools": ["claude_code"], "due": "2026-10-30", "last_activity": 1.0, "pr": None,
                                            "progress": {"percent": 55, "agent_says_percent": 100, "confidence": "high",
                                                         "blockers": [], "doing": [{"text": "Committing", "evidence_ids": ["e1"]}],
                                                         "next": [{"text": "Push", "evidence_ids": []}], "done": [{"text": "x"}] * 6},
                                            "editing": [{"repo": "acme-web", "file": "src/a.py", "member": "Yang", "tool": "codex"}]}],
             "overlaps": [{"repo": "acme-web", "file": "src/a.py", "who": [{"member": "Yang"}, {"member": "Asha"}]}]}
    live = [{"turn": "turn-0001", "chat": "c-1", "agent": "agent-s", "message": "Push it", "asking": True, "now": None,
             "ask": {"id": "c9", "name": "write_file", "args": {"path": "a.py", "content": "x" * 9000}}}]
    def call(method, path, body=None):  # the stand-in API, plus the board and a turn waiting on a question
        if path.startswith("/api/cloud/board?team="):
            api.calls.append((method, path, body))
            return board
        if path == "/api/turns" and method == "GET":
            return {"turns": live}
        if path == f"/api/cloud/approvals?team={TEAM}":  # this laptop's person leads: a member's agent waits on their yes
            return {"approvals": [{"id": "a1", "from": {"id": "u2", "name": "Asha"}, "what": "Close T-3", "detail": "", "rule": "board"}]}
        return api(method, path, body)
    r = remote.Remote(call, relay=lambda: "wss://relay", team=lambda: TEAM, relay_cls=FakeRelay)
    r.sync()
    relay = FakeRelay.made[0]
    relay.on_message(phone(key, pid, {"t": "board"}, id="b1"))
    relay.on_message(phone(key, pid, {"t": "hello"}, id="h1"))
    assert wait_for(lambda: len(relay.sent) == 2)
    got = {m["re"]: m for m in heard(relay, key, pid)}
    [t] = got["b1"]["tasks"]
    assert got["b1"]["room"] == "Loopers" and t["percent"] == 55 and t["says"] == 100 and t["doing"] == ["Committing"] and t["next"] == ["Push"]
    assert "done" not in t and "progress" not in t  # a phone needs the gist, not the evidence ids
    assert t["editing"] == ["src/a.py"] and got["b1"]["overlaps"] == [{"file": "acme-web/src/a.py", "who": ["Yang", "Asha"]}]
    ask = got["h1"]["live"][0]["ask"]
    assert ask["id"] == "c9" and len(ask["args"]["content"]) < 4100  # what waits, cut for a phone
    assert got["h1"]["asks"] == [{"id": "a1", "from": "Asha", "what": "Close T-3", "detail": "", "rule": "board"}]
    r.online[pid] = time.time()
    relay.sent.clear()
    r.push_live(every=0.01, rounds=3)  # an open phone hears about running turns once, not every round
    pushed = heard(relay, key, pid)
    assert [m["t"] for m in pushed] == ["live"] and pushed[0]["asks"][0]["what"] == "Close T-3"


def test_the_phone_reads_a_tasks_notes_and_leaves_one(home):
    pid, key = paired()
    api, posted = Api(), []
    stored = [{"id": 1, "from": {"id": "u2", "name": "Asha"}, "via": "agent", "to": None, "task": "T-3", "text": "Renamed /v1/session", "at": 1.0},
              {"id": 0, "from": {"id": "u2", "name": "Asha"}, "via": "person", "to": {"id": "u1", "name": "Yang"}, "task": "T-3",
               "text": "Mine until 5", "at": 0.5}]
    def call(method, path, body=None):
        if path == "/api/boot":
            return {"signed_in": True, "user": {"id": "u1", "name": "Yang"}}
        if path == f"/api/cloud/messages?team={TEAM}" and method == "POST":
            posted.append(body)
            stored.insert(0, {"id": 2, "from": {"id": "u1", "name": "Yang"}, "via": "person", "to": {"id": "u2", "name": "Asha"},
                              "task": "T-3", "text": body["text"], "at": 2.0})
            return {"messages": stored[:1], "skipped": []}
        if path == f"/api/cloud/messages?team={TEAM}&box=all&task=T-3":
            return {"messages": stored}  # newest first, as the hub gives them
        return api(method, path, body)
    r = remote.Remote(call, relay=lambda: "wss://relay", team=lambda: TEAM, relay_cls=FakeRelay)
    r.sync()
    relay = FakeRelay.made[0]
    relay.on_message(phone(key, pid, {"t": "notes", "task": "T-3"}, id="n1"))
    assert wait_for(lambda: len(relay.sent) == 1)
    relay.on_message(phone(key, pid, {"t": "note", "task": "T-3", "to": "Asha", "text": "Thanks, rebasing"}, id="n2"))
    relay.on_message(phone(key, pid, {"t": "notes", "task": "../board"}, id="n3"))
    assert wait_for(lambda: len(relay.sent) == 3)
    got = {m["re"]: m for m in heard(relay, key, pid)}
    assert got["n1"]["notes"] == [{"from": "Asha", "mine": False, "agent": False, "to": "you", "text": "Mine until 5", "at": 0.5},
                                  {"from": "Asha", "mine": False, "agent": True, "to": None, "text": "Renamed /v1/session", "at": 1.0}]
    assert posted == [{"to": "Asha", "text": "Thanks, rebasing", "task": "T-3"}]
    assert [(n["from"], n["mine"], n["to"]) for n in got["n2"]["notes"]] == [("Asha", False, "you"), ("Asha", False, None), ("Yang", True, "Asha")]
    assert got["n3"]["t"] == "error"


def test_long_output_is_cut_for_the_phone():
    e = remote.slim({"kind": "tool", "result": "x" * 5000, "args": {"content": "y" * 9000, "path": "a.py"}})
    assert len(e["result"]) < 1600 and len(e["args"]["content"]) < 4100 and e["args"]["path"] == "a.py"


def test_settings_pair_a_phone_and_list_live_turns(home):
    state = server.State("https://hub.example", port=47124, key="k")
    c = TestClient(server.create(state), base_url="http://127.0.0.1:47124")
    c.headers["X-App-Key"] = "k"
    assert c.get("/api/remote").json() == {"on": False, "ready": False, "phones": []}
    q = c.post("/api/remote/pair").json()
    assert q["url"].startswith("https://hub.example/remote/#p=") and q["qr"].startswith("<svg") and "viewBox" in q["qr"]
    assert c.get("/api/remote").json()["on"] is True
    assert c.put("/api/remote", json={"enabled": False}).json()["on"] is False
    c.delete(f"/api/remote/phones/{q['id']}")
    assert store.remote()["phones"] == []
    push = {"kind": "tool", "id": "call-1", "name": "git_push", "args": {"repo": "acme"}}
    state.turns["t-1"] = SimpleNamespace(id="t-1", chat={"id": "c-1"}, agent={"id": "agent-s"}, message="Push it", done=False,
                                         decisions={"call-1": threading.Event()}, waiting={"call-1": "change"}, events=[{**push, "status": "asking"}])
    test = {"kind": "tool", "id": "call-2", "name": "run_command", "args": {"command": "npm test"}}
    state.turns["t-2"] = SimpleNamespace(id="t-2", chat={"id": "c-2"}, agent={"id": "agent-s"}, message="Test it", done=False,
                                         decisions={}, waiting={}, events=[{**push, "status": "done"}, {**test, "status": "running"}])
    state.turns["t-3"] = SimpleNamespace(id="t-3", chat={"id": "c-3"}, agent={"id": "agent-s"}, message="Done one", decisions={},
                                         waiting={}, events=[], done=True)
    state.turns["t-4"] = SimpleNamespace(id="t-4", chat={"id": "c-4"}, agent={"id": "agent-s"}, message="Push it too", done=False,
                                         decisions={"call-4": threading.Event()}, waiting={"call-4": "lead"}, events=[{**push, "id": "call-4", "status": "asking"}])
    t1, t2, t4 = c.get("/api/turns").json()["turns"]
    assert t1["asking"] and t1["ask"] == {"id": "call-1", "name": "git_push", "args": {"repo": "acme"}, "group": None, "access": None}
    assert not t2["asking"] and t2["ask"] is None and t2["now"]["name"] == "run_command"  # the step it's on, not one that's done
    assert not t4["asking"] and t4["ask"] is None  # waiting for a lead's yes, not this person's: not in their Needs you

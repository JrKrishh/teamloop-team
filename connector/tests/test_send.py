"""The privacy boundary (PLAN.md M9): what a real HTTP hub receives, checked against canary text."""

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from teamloop import normalize, send, spool, summarize

CANARY = "CANARY-raw-agent-text-7f3a"


class Hub:
    """Stand-in hub speaking ccbridge auth: /v1/join hands out a session; /v1/events records what arrives."""

    def __init__(self, status=200):
        self.bodies, self.auth, self.sessions, self.joins, self.status = [], [], [], 0, status
        self.expire_next = False
        hub = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"])).decode()
                if self.path == "/v1/join":
                    hub.joins += 1
                    return self._reply(200, json.dumps({"session_id": f"sess-{hub.joins}"}).encode())
                if hub.expire_next:
                    hub.expire_next = False
                    return self._reply(401, b"{}")
                hub.auth.append(self.headers.get("Authorization"))
                hub.sessions.append(self.headers.get("X-CCBridge-Session"))
                hub.bodies.append(body)
                self._reply(hub.status, b"{}")

            def _reply(self, code, payload):
                self.send_response(code)
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"


def config(url):
    return {"url": url, "room": "team-room", "token": "room-token", "name": "yang", "identity_key": "k" * 32}


@pytest.fixture
def hub(teamloop_home):
    h = Hub()
    teamloop_home.mkdir(parents=True, exist_ok=True)
    (teamloop_home / "config.json").write_text(json.dumps(config(h.url)))
    yield h
    h.server.shutdown()


def spool_turn(text=f"Fixed add(). {CANARY}"):
    spool.append({**normalize.event("turn_end", "claude_code", {"session_id": "s1"}, local={"text": text}), "task": "T-3"})
    spool.append({**normalize.event("tool", "claude_code", {"session_id": "s1"}, {"tool": "Edit", "file": "calc.py"}), "task": "T-3"})


def by_kind(events, kind):
    return next(e for e in events if e["kind"] == kind)


def fake_summary(text, facts):
    assert CANARY in text  # the summarizer is the only thing that sees local text
    return {"summary": "Fixed add() so the test passes.", "status": "done", "model": "fake"}


def test_hub_gets_summary_never_local_text(hub):
    spool_turn()
    assert send.send_once(summarizer=fake_summary) == (2, None)
    [body] = hub.bodies
    assert CANARY not in body and '"local"' not in body
    events = json.loads(body)["events"]
    turn = by_kind(events, "turn_end")
    assert turn["summary"] == "Fixed add() so the test passes." and turn["status"] == "done"
    assert all(e["member"] == "yang" and e["task"] == "T-3" for e in events)
    assert hub.auth == ["Bearer room-token"] and hub.sessions == ["sess-1"]
    assert spool.pending() == []  # sent events leave the spool


def test_hub_down_keeps_the_spool(hub):
    hub.status = 500
    spool_turn()
    sent, err = send.send_once(summarizer=fake_summary)
    assert sent == 0 and "500" in err and len(spool.pending()) == 2


def test_summarizer_failure_does_not_block_sending(hub):
    def broken(text, facts):
        raise TimeoutError("model slow")

    spool_turn()
    assert send.send_once(summarizer=broken) == (2, None)
    event = by_kind(json.loads(hub.bodies[0])["events"], "turn_end")
    assert event["summary_error"] == "TimeoutError" and "summary" not in event and CANARY not in hub.bodies[0]


def test_not_logged_in(teamloop_home):
    spool_turn()
    sent, err = send.send_once(summarizer=fake_summary)
    assert sent == 0 and "login" in err and len(spool.pending()) == 2


def test_parse_clips_validates_and_redacts():
    out = summarize.parse(json.dumps({"summary": "x" * 300, "status": "weird"}))
    assert len(out["summary"]) == 160 and out["status"] == "progress"
    leaked = summarize.parse(json.dumps({"summary": "Set key ghp_" + "a" * 36, "status": "done"}))
    assert "ghp_" not in leaked["summary"]
    with pytest.raises(ValueError):
        summarize.parse(json.dumps({"summary": "  ", "status": "done"}))


def test_off_means_no_model_call(monkeypatch):
    monkeypatch.setenv("TEAMLOOP_SUMMARIZER", "off")
    assert summarize.summarize("anything") is None


def test_a_laptop_on_the_hosted_hub_gets_its_summaries_there(teamloop_home, monkeypatch):
    from teamloop import login

    monkeypatch.delenv("TEAMLOOP_SUMMARIZER")
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    assert summarize.provider() == "ollama"  # not connected: local, or nothing
    teamloop_home.mkdir(parents=True, exist_ok=True)
    (teamloop_home / "config.json").write_text(json.dumps({"mode": "cloud", "url": "https://hub.test", "token": "tl_x"}))
    asked = []
    monkeypatch.setattr(login, "request", lambda cfg, method, path, body: asked.append((cfg["token"], method, path, body)) or
                        {"summary": "Fixed add() with key ghp_" + "a" * 36, "status": "done", "model": "nebius:nvidia/Nemotron-3_5-Lightning"})
    out = summarize.summarize("Fixed add(); 3 tests pass.", {"tool": "Bash"})
    assert summarize.provider() == "hub" and asked == [("tl_x", "POST", "/v1/summarize", {"text": "Fixed add(); 3 tests pass.", "facts": {"tool": "Bash"}})]
    assert out["status"] == "done" and "ghp_" not in out["summary"] and out["model"].endswith("Lightning")  # redacted here too
    monkeypatch.setenv("TEAMLOOP_SUMMARIZER", "ollama")
    assert summarize.provider() == "ollama"  # keeping the message on the laptop is one setting away


def test_one_sender_per_laptop(teamloop_home):
    assert send.my_turn() and send.my_turn()  # we hold it, and keep holding it
    (teamloop_home / "sender.lock").write_text("999999")  # another live sender
    assert not send.my_turn()
    old = time.time() - 120
    os.utime(teamloop_home / "sender.lock", (old, old))  # ...whose heartbeat stopped
    assert send.my_turn()


def test_daemon_thread_sends_and_stops(hub, monkeypatch):
    monkeypatch.setattr(summarize, "summarize", fake_summary)
    spool_turn()
    stop, lines = threading.Event(), []
    t = threading.Thread(target=send.daemon, kwargs={"every": 0.05, "log": lines.append, "stop": stop})
    t.start()
    for _ in range(100):
        if not spool.pending():
            break
        time.sleep(0.05)
    stop.set()
    t.join(5)
    assert spool.pending() == [] and not t.is_alive() and any("sent 2" in line for line in lines)
    assert by_kind(json.loads(hub.bodies[0])["events"], "turn_end")["summary_model"] == "fake"


def test_spool_keeps_order_within_a_tick(monkeypatch):
    monkeypatch.setattr(spool.time, "time_ns", lambda: 1_791_830_000_000_000_000)  # a frozen, coarse clock
    kinds = ["session_start", "tool", "turn_end", "session_end"]
    for k in kinds:
        spool.append(normalize.event(k, "claude_code", {}))
    assert [spool.read(p)["kind"] for p in spool.pending()] == kinds


def test_expired_session_rejoins_once(hub):
    spool_turn()
    send.send_once(summarizer=fake_summary)
    spool_turn()
    hub.expire_next = True  # the hub restarted: the old session is gone
    assert send.send_once(summarizer=fake_summary) == (2, None)
    assert hub.joins == 2 and hub.sessions == ["sess-1", "sess-2"]


def test_invite_round_trip_and_bad_invites():
    from teamloop import login

    inv = login.invite("https://hub.example.com/", "team-room", "tok")
    assert login.decode(inv) == ("https://hub.example.com", "team-room", "tok")
    for bad in ("nonsense", login.encode("ftp://x", "team-room", "t"), login.encode("https://x", "a b", "t")):
        with pytest.raises(ValueError):
            login.decode(bad)


def test_login_joins_and_keeps_identity_on_relogin(hub, teamloop_home):
    from teamloop import login

    (teamloop_home / "config.json").unlink()
    inv = login.encode(hub.url, "team-room", "room-token")
    assert login.login(inv, "yang") == 0
    first = json.loads((teamloop_home / "config.json").read_text())
    assert login.login(inv, "yang") == 0
    again = json.loads((teamloop_home / "config.json").read_text())
    assert first["identity_key"] == again["identity_key"] and len(first["identity_key"]) >= 32


def test_batches_stay_under_the_hub_body_limit(hub):
    big = "x" * 1400  # each event about 1.6 KB once wrapped
    for _ in range(50):
        spool.append({**normalize.event("self_report", "mcp", {}), "task": "T-3", "report": {"done": [big[:150]] * 5,
                      "doing": big[:150], "next": [big[:150]] * 5, "percent": 10}})
    sent, err = send.send_once(summarizer=fake_summary)
    assert err is None and 0 < sent < 50 and len(hub.bodies[0].encode()) < 64 * 1024
    assert len(spool.pending()) == 50 - sent  # the rest waits for the next batch

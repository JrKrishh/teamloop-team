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
    def __init__(self, status=200):
        self.bodies, self.auth, self.status = [], [], status
        hub = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                hub.auth.append(self.headers.get("Authorization"))
                hub.bodies.append(self.rfile.read(int(self.headers["Content-Length"])).decode())
                self.send_response(hub.status)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"


@pytest.fixture
def hub(teamloop_home):
    h = Hub()
    teamloop_home.mkdir(parents=True, exist_ok=True)
    (teamloop_home / "config.json").write_text(json.dumps({"hub": h.url, "token": "member-token", "member": "yang"}))
    yield h
    h.server.shutdown()


def spool_turn(text=f"Fixed add(). {CANARY}"):
    spool.append({**normalize.event("turn_end", "claude_code", {"session_id": "s1"}, local={"text": text}), "task": "T-3"})
    spool.append({**normalize.event("tool", "claude_code", {"session_id": "s1"}, {"tool": "Edit", "file": "calc.py"}), "task": "T-3"})


def fake_summary(text, facts):
    assert CANARY in text  # the summarizer is the only thing that sees local text
    return {"summary": "Fixed add() so the test passes.", "status": "done", "model": "fake"}


def test_hub_gets_summary_never_local_text(hub):
    spool_turn()
    assert send.send_once(summarizer=fake_summary) == (2, None)
    [body] = hub.bodies
    assert CANARY not in body and '"local"' not in body
    events = json.loads(body)["events"]
    assert events[0]["summary"] == "Fixed add() so the test passes." and events[0]["status"] == "done"
    assert all(e["member"] == "yang" and e["task"] == "T-3" for e in events)
    assert hub.auth == ["Bearer member-token"]
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
    event = json.loads(hub.bodies[0])["events"][0]
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
    assert json.loads(hub.bodies[0])["events"][0]["summary_model"] == "fake"

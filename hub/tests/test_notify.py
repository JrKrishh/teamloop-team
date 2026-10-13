"""Blocker pings: one per new blocked event, mentions defused, Discord and Slack shapes."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from fastapi.testclient import TestClient

from hub import notify
from hub.app import create
from tests.test_team import fake_chat, golden, member


def webhook():
    got = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            got.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, got


def test_blocked_event_pings_once(monkeypatch):
    server, got = webhook()
    monkeypatch.setenv("HUB_NOTIFY_WEBHOOK", f"http://127.0.0.1:{server.server_port}/hook")
    client = TestClient(create(":memory:", chat=fake_chat, start_worker=False))
    s = member(client, "sourabh")
    events = golden("synthetic_blocked_migration.json")
    client.post("/v1/events", json={"events": events}, headers=s)
    client.post("/v1/events", json={"events": events}, headers=s)  # redelivery
    for _ in range(50):
        if got:
            break
        time.sleep(0.05)
    time.sleep(0.2)
    server.shutdown()
    assert len(got) == 1
    msg = got[0]
    assert msg["content"] == msg["text"] and msg["allowed_mentions"] == {"parse": []}
    assert msg["content"].startswith("[TeamLoop · teamloop] T-11 is blocked (sourabh's agent, needs access):")


def test_mentions_are_defused():
    text = notify.message("teamloop", {"task": "T-1", "member": "eve", "report": {"reason": "ping @everyone now", "needs": "person"}})
    assert "@everyone" not in text and "@‍everyone" in text


def test_no_webhook_no_ping(monkeypatch):
    monkeypatch.delenv("HUB_NOTIFY_WEBHOOK", raising=False)
    notify.blocked("teamloop", {"task": "T-1"})  # nothing to call, nothing raised

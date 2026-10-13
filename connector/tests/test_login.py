"""`teamloop login` against a stand-in cloud hub: the device flow, then events sent with the connector token."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from teamloop import doctor, login, send, spool
from tests.test_send import spool_turn


class CloudHub:
    def __init__(self, approve_after=2, outcome="approved"):
        self.polls, self.auth, self.bodies = 0, [], []
        hub = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
                if self.path == "/v1/device/start":
                    return self._json({"device_code": "dev-123", "user_code": "BCDF-GHJK", "interval": 3, "expires_in": 900,
                                       "verify_url": f"{hub.url}/device?code=BCDF-GHJK"})
                hub.auth.append(self.headers.get("Authorization"))
                hub.bodies.append(body)
                self._json({"accepted": 1, "duplicates": 0})

            def do_GET(self):
                url = urlparse(self.path)
                assert url.path == "/v1/device/poll" and parse_qs(url.query)["device_code"] == ["dev-123"]
                hub.polls += 1
                if hub.polls < approve_after:
                    return self._json({"status": "pending"})
                if outcome != "approved":
                    return self._json({"status": outcome})
                self._json({"status": "approved", "token": "tl_secret", "team": {"id": "t1", "name": "Loopers"},
                            "name": "Yang", "url": hub.url + "/"})

            def _json(self, data):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"


@pytest.fixture
def cloud():
    hubs = []
    yield lambda **kw: hubs.append(CloudHub(**kw)) or hubs[-1]
    for h in hubs:
        h.server.shutdown()


def test_device_login_saves_a_cloud_connection(cloud, capsys):
    hub, opened, waits = cloud(), [], []
    assert login.device_login(hub.url, open_url=opened.append, sleep=waits.append) == 0
    assert opened == [f"{hub.url}/device?code=BCDF-GHJK"] and waits == [3, 3] and hub.polls == 2
    cfg = json.loads((spool.home() / "config.json").read_text())
    assert cfg == {"mode": "cloud", "url": hub.url, "token": "tl_secret", "name": "Yang", "team": {"id": "t1", "name": "Loopers"}}
    out = capsys.readouterr().out
    assert "BCDF-GHJK" in out and "Connected to Loopers as Yang" in out and "tl_secret" not in out
    assert any(r[0] == "ok" and "team Loopers" in r[1] for r in doctor.checks(spool.home()))


def test_an_expired_code_saves_nothing(cloud, capsys):
    hub = cloud(approve_after=1, outcome="expired")
    assert login.device_login(hub.url, open_url=lambda u: None, sleep=lambda s: None) == 1
    assert not (spool.home() / "config.json").exists() and "expired" in capsys.readouterr().out


def test_events_go_out_with_the_connector_token_only(cloud):
    hub = cloud()
    login.device_login(hub.url, open_url=lambda u: None, sleep=lambda s: None)
    spool_turn("Fixed add().")
    assert send.send_once(summarizer=lambda t, f: None)[1] is None
    assert hub.auth == ["Bearer tl_secret"]  # no room token, no /v1/join
    assert "local" not in hub.bodies[0] and "Fixed add()." not in hub.bodies[0]

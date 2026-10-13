"""Retries and fallback against a stand-in OpenAI-compatible server."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from agent_s import llm


def server(script):
    """script: list of (status, models_seen) responses in order."""
    seen = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(body["model"])
            status = script[min(len(seen), len(script)) - 1]
            self.send_response(status)
            self.end_headers()
            if status == 200:
                self.wfile.write(json.dumps({"choices": [{"message": {"content": json.dumps({"ok": True})}}]}).encode())

        def log_message(self, *a):
            pass

    s = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s, seen


@pytest.fixture
def provider(monkeypatch):
    def use(url):
        cfg = {"url": url, "key": None, "extra": {}, "models": {"progress": "mid", "qa": "mid", "digest": "big"}}
        monkeypatch.setitem(llm.PROVIDERS, "test", cfg)
        monkeypatch.setenv("AGENT_S_PROVIDER", "test")
        monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    return use


def test_retries_once_after_a_server_error(provider):
    s, seen = server([503, 200])
    provider(f"http://127.0.0.1:{s.server_port}/v1/chat/completions")
    assert llm.chat_json("progress", [], {}) == {"ok": True} and seen == ["mid", "mid"]


def test_big_model_falls_back_to_the_progress_model(provider):
    s, seen = server([429, 503, 200])
    provider(f"http://127.0.0.1:{s.server_port}/v1/chat/completions")
    assert llm.chat_json("digest", [], {}) == {"ok": True} and seen == ["big", "big", "mid"]


def test_client_errors_are_not_retried(provider):
    s, seen = server([400, 200])
    provider(f"http://127.0.0.1:{s.server_port}/v1/chat/completions")
    with pytest.raises(llm.urllib.error.HTTPError):
        llm.chat_json("progress", [], {})
    assert seen == ["mid"]

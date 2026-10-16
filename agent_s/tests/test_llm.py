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
                self.wfile.write(json.dumps({"choices": [{"message": {"content": json.dumps({"ok": True})}}],
                                             "usage": {"prompt_tokens": 120, "completion_tokens": 30}}).encode())

        def log_message(self, *a):
            pass

    s = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s, seen


@pytest.fixture
def provider(monkeypatch):
    def use(url):
        cfg = {"url": url, "key": None, "extra": {}, "models": {"progress": "mid", "qa": "mid", "digest": "big", "agent": "mid", "summary": "small"}}
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


def test_effort_sets_how_hard_the_model_thinks(provider):
    bodies = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            bodies.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode())

        def log_message(self, *a):
            pass

    s = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    provider(f"http://127.0.0.1:{s.server_port}/v1/chat/completions")
    llm.PROVIDERS["test"]["extra"] = {"reasoning_effort": "low"}
    hi = [{"role": "user", "content": "hi"}]
    llm.chat_tools(hi, [])
    with llm.effort("high"):
        llm.chat_tools(hi, [])
    with llm.effort("turbo"):  # not a level: the provider's own
        llm.chat_tools(hi, [])
    assert [b["reasoning_effort"] for b in bodies] == ["low", "high", "low"]


def test_the_meter_counts_every_answered_call(provider):
    s, seen = server([503, 200, 200])
    provider(f"http://127.0.0.1:{s.server_port}/v1/chat/completions")
    with llm.meter() as m:
        llm.chat_json("progress", [], {})  # a failed try and an answer: one call counted
        step = llm.chat_tools([{"role": "user", "content": "hi"}], [])
    assert step["usage"] == {"in": 120, "out": 30}
    assert m == {"calls": 2, "in": 240, "out": 60, "model": "test:mid"}
    llm.chat_tools([{"role": "user", "content": "hi"}], [])  # outside a meter: nothing to count into
    assert m["calls"] == 2


def test_summaries_skip_thinking(provider):
    """One line from one message: thinking first used the whole budget and retried (see llm.NO_THINK)."""
    bodies = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            bodies.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"choices": [{"message": {"content": json.dumps({"ok": True})}}]}).encode())

        def log_message(self, *a):
            pass

    s = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    provider(f"http://127.0.0.1:{s.server_port}/v1/chat/completions")
    llm.PROVIDERS["test"].update(extra={"reasoning_effort": "low"}, no_think={"reasoning_effort": "none"})
    llm.chat_json("summary", [], {})
    llm.chat_json("progress", [], {})
    with llm.effort("high"):  # an effort someone picked still wins
        llm.chat_json("summary", [], {})
    assert [(b["model"], b["reasoning_effort"]) for b in bodies] == [("small", "none"), ("mid", "low"), ("small", "high")]

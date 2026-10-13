"""SSE board stream against a real uvicorn server: a posted event reaches an open board without a refresh."""

import json
import threading
import time

import httpx

from hub import team
from tests.test_e2e import live_hub  # noqa: F401  (fixture)
from tests.test_team import TOKEN, golden


def test_posted_event_is_pushed_to_an_open_board(live_hub, monkeypatch):  # noqa: F811
    monkeypatch.setattr(team, "STREAM_POLL_SECONDS", 0.1)
    app, url = live_hub
    r = httpx.post(f"{url}/v1/join", json={"room": "teamloop", "display_name": "yang", "identity_key": "k" * 24},
                   headers={"Authorization": f"Bearer {TOKEN}"})
    yang = {"Authorization": f"Bearer {TOKEN}", "X-CCBridge-Room": "teamloop", "X-CCBridge-Session": r.json()["session_id"]}
    boards, stop = [], threading.Event()

    def listen():
        with httpx.stream("GET", f"{url}/v1/stream", headers=yang, timeout=10) as s:
            for line in s.iter_lines():
                if line.startswith("data: "):
                    boards.append(json.loads(line[6:]))
                if stop.is_set():
                    return

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    for _ in range(50):
        if boards:
            break
        time.sleep(0.1)
    assert boards and boards[0]["tasks"] == []  # the current board arrives at once

    httpx.post(f"{url}/v1/events", json={"events": golden("real_fix_add_done.json")}, headers=yang)
    for _ in range(50):
        if len(boards) > 1:
            break
        time.sleep(0.1)
    stop.set()
    assert len(boards) > 1 and boards[-1]["tasks"][0]["task"] == "T-3"  # pushed, no refresh


def test_stream_needs_auth(live_hub):  # noqa: F811
    _, url = live_hub
    assert httpx.get(f"{url}/v1/stream", timeout=5).status_code == 401

"""Connector -> real HTTP hub -> Agent S -> board, in one process. Only the model is faked."""

import json
import socket
import threading
import time

import pytest
import uvicorn

from hub.app import create
from tests.test_team import fake_chat

teamloop = pytest.importorskip("teamloop")
from teamloop import login, normalize, send, spool  # noqa: E402


@pytest.fixture
def live_hub(monkeypatch):
    monkeypatch.setenv("HUB_SECURE_COOKIE", "0")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = create(":memory:", chat=fake_chat, start_worker=False)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield app, f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(5)


def test_connector_to_board(live_hub, tmp_path, monkeypatch):
    app, url = live_hub
    monkeypatch.setenv("TEAMLOOP_HOME", str(tmp_path / "tl"))
    send._session.clear()
    assert login.login(login.encode(url, "teamloop", "room-token-123"), "yang") == 0

    spool.append({**normalize.event("task_start", "mcp", {}, {"title": "Fix add()"}), "task": "T-3"})
    spool.append({**normalize.event("turn_end", "claude_code", {"session_id": "s"}, local={"text": "SECRET-local-words"}),
                  "task": "T-3"})
    fake = lambda text, facts: {"summary": "Fixed add(); the test passes.", "status": "done", "model": "fake"}  # noqa: E731
    assert send.send_once(summarizer=fake) == (2, None)
    assert spool.pending() == []

    assert app.state.refresh_progress(time.time() + 31) == ["teamloop/T-3"]
    with app.state.conn as c:
        bodies = " ".join(r[0] for r in c.execute("SELECT body FROM events"))
    assert "SECRET-local-words" not in bodies and "Fixed add(); the test passes." in bodies
    board = app.state.build_board("teamloop")
    [task] = board["tasks"]
    assert task["title"] == "Fix add()" and task["members"] == ["yang"] and task["progress"]["percent"] == 95
    assert board["members"][0]["active"] is True

"""Public demo room: readable without sign-in, never writable, Q&A rate-limited."""

import pytest
from fastapi.testclient import TestClient

from hub import demo
from hub.app import create
from tests.test_team import fake_chat, golden


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("HUB_DEMO_ROOM", "demo")
    monkeypatch.setenv("HUB_DEMO_ASKS_PER_10MIN", "2")
    app = create(":memory:", chat=fake_chat, start_worker=False)
    assert demo.seed(app, "demo") > 0 and demo.seed(app, "demo") == 0  # seeding twice is a no-op
    return TestClient(app)


def test_demo_board_is_public_and_live_looking(client):
    b = client.get("/v1/board").json()
    assert b["demo"] is True and b["room"] == "demo"
    status = {t["task"]: t["status"] for t in b["tasks"]}
    assert status == {"T-21": "in_progress", "T-22": "blocked", "T-19": "review", "T-17": "done"}
    assert all(t["progress"] and t["progress"]["model"] for t in b["tasks"])  # real Agent S output, model recorded
    assert any(m["active"] for m in b["members"]) and "github" not in [m["name"] for m in b["members"]]


def test_demo_is_read_only(client):
    assert client.post("/v1/events", json={"events": golden("real_fix_add_done.json")}).status_code == 401


def test_demo_questions_are_rate_limited(client):
    codes = [client.post("/v1/ask", json={"question": "Anything blocked?"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]

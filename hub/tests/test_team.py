"""TeamLoop endpoints on the relay: events in, Agent S progress, board, sign-in, Q&A. Agent S's model is faked."""

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hub.app import create

GOLDEN = Path(__file__).parents[2] / "agent_s" / "golden"
TOKEN = "room-token-123"


def golden(name):
    return json.loads((GOLDEN / name).read_text(encoding="utf-8"))["events"]


def fake_chat(job, messages, schema):
    if job == "qa":
        return {"answerable": True, "answer": "T-11 is blocked on database access (e1).", "citations": ["e1"], "unknowns": []}
    return {"done": [{"text": "fixed add()", "evidence": ["e3"]}], "doing": [], "next": [], "blockers": [],
            "percent": 95, "confidence": "high"}


@pytest.fixture
def hub(monkeypatch):
    monkeypatch.setenv("HUB_SECURE_COOKIE", "0")  # the test client talks plain http
    app = create(":memory:", chat=fake_chat, start_worker=False)
    return app, TestClient(app)


def member(client, name, room="teamloop"):
    r = client.post("/v1/join", json={"room": room, "display_name": name, "identity_key": f"key-of-{name}".ljust(24, "x")},
                    headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {TOKEN}", "X-CCBridge-Room": room, "X-CCBridge-Session": r.json()["session_id"]}


def test_events_are_idempotent_and_owned_by_the_session(hub):
    app, client = hub
    yang = member(client, "yang")
    events = golden("real_fix_add_done.json")
    events[0] = {**events[0], "member": "someone-else"}
    r = client.post("/v1/events", json={"events": events}, headers=yang)
    assert r.json() == {"accepted": len(events), "duplicates": 0}
    assert client.post("/v1/events", json={"events": events}, headers=yang).json()["duplicates"] == len(events)
    board = client.get("/v1/board", headers=yang).json()
    [task] = board["tasks"]
    assert task["task"] == "T-3" and task["members"] == ["yang"] and task["tools"] == ["claude_code", "mcp"]


def test_local_text_is_refused_and_bad_events_rejected(hub):
    _, client = hub
    yang = member(client, "yang")
    e = golden("real_fix_add_done.json")[0]
    assert client.post("/v1/events", json={"events": [{**e, "local": {"text": "x"}}]}, headers=yang).status_code == 400
    assert client.post("/v1/events", json={"events": [{**e, "id": "not-hex"}]}, headers=yang).status_code == 422
    assert client.post("/v1/events", json={"events": [e]}).status_code == 401  # no session, no entry


def test_peer_text_is_sanitized(hub):
    _, client = hub
    yang = member(client, "yang")
    e = {**golden("synthetic_early_sse.json")[-1], "summary": "Done​​ with the stream handler"}
    client.post("/v1/events", json={"events": [e]}, headers=yang)
    recent = client.get("/v1/board", headers=yang).json()["tasks"][0]["recent"]
    assert "​" not in json.dumps(recent)


def test_progress_snapshot_after_quiet_period(hub):
    app, client = hub
    yang = member(client, "yang")
    client.post("/v1/events", json={"events": golden("real_fix_add_done.json")}, headers=yang)
    import time

    assert app.state.refresh_progress(time.time()) == []  # still within the debounce window
    assert app.state.refresh_progress(time.time() + 31) == ["teamloop/T-3"]
    assert app.state.refresh_progress(time.time() + 62) == []  # nothing new since
    progress = client.get("/v1/board", headers=yang).json()["tasks"][0]["progress"]
    assert progress["percent"] == 95 and progress["done"][0]["text"] == "fixed add()"


def test_blocked_task_shows_blocked(hub):
    _, client = hub
    sourabh = member(client, "sourabh")
    client.post("/v1/events", json={"events": golden("synthetic_blocked_migration.json")}, headers=sourabh)
    [task] = client.get("/v1/board", headers=sourabh).json()["tasks"]
    assert task["status"] == "blocked" and task["title"] == "Add progress_snapshots table"


def test_board_cookie_sign_in(hub):
    _, client = hub
    member(client, "yang")  # creates the room (trust on first use, as in ccbridge)
    assert client.post("/v1/board/login", json={"room": "teamloop", "token": "wrong"}).status_code == 403
    assert client.get("/v1/board").status_code == 401
    assert client.post("/v1/board/login", json={"room": "teamloop", "token": TOKEN}).status_code == 200
    assert client.get("/v1/board").json()["room"] == "teamloop"  # the cookie is enough


def test_ask_answers_with_citations(hub):
    _, client = hub
    sourabh = member(client, "sourabh")
    client.post("/v1/events", json={"events": golden("synthetic_blocked_migration.json")}, headers=sourabh)
    out = client.post("/v1/ask", json={"question": "Anything blocked?"}, headers=sourabh).json()
    assert out["answer"] == "T-11 is blocked on database access." and len(out["citations"]) == 1


def test_rooms_are_isolated(hub):
    _, client = hub
    a, b = member(client, "yang", "team-a"), member(client, "eve", "team-b")
    client.post("/v1/events", json={"events": golden("real_fix_add_done.json")}, headers=a)
    assert client.get("/v1/board", headers=b).json()["tasks"] == []


def test_board_page_and_mascots_are_served(hub):
    _, client = hub
    page = client.get("/")
    assert page.status_code == 200 and "TeamLoop" in page.text
    assert not re.search(r"\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML", page.text)  # peer text is untrusted
    assert client.get("/static/mascot/agent-s/think.webp").headers["content-type"] == "image/webp"


def test_untitled_task_takes_its_title_from_the_branch(hub):
    _, client = hub
    s = member(client, "sourabh")
    e = {**golden("synthetic_early_sse.json")[2], "id": "f" * 32, "task": "T-7", "branch": "T-7-add-multiply"}
    client.post("/v1/events", json={"events": [e]}, headers=s)
    assert client.get("/v1/board", headers=s).json()["tasks"][0]["title"] == "Add multiply"


def test_members_are_rate_limited(monkeypatch):
    from hub import team

    monkeypatch.setattr(team, "POSTS_PER_MINUTE", 2)
    client = TestClient(create(":memory:", chat=fake_chat, start_worker=False))
    yang = member(client, "yang")
    e = golden("real_fix_add_done.json")
    codes = [client.post("/v1/events", json={"events": [e[i]]}, headers=yang).status_code for i in range(3)]
    assert codes == [200, 200, 429]


def test_oversized_event_is_refused(hub):
    _, client = hub
    yang = member(client, "yang")
    e = {**golden("real_fix_add_done.json")[0], "facts": {"note": "x" * 9000}}
    assert client.post("/v1/events", json={"events": [e]}, headers=yang).status_code == 413


def test_old_events_and_extra_snapshots_are_pruned(hub):
    import time

    app, client = hub
    yang = member(client, "yang")
    client.post("/v1/events", json={"events": golden("real_fix_add_done.json")}, headers=yang)
    with app.state.lock:
        for i in range(25):
            app.state.conn.execute("INSERT INTO snapshots VALUES ('teamloop', 'T-3', ?, '{}')", (time.time() + i,))
        app.state.conn.commit()
    assert app.state.prune_events(time.time()) == 0  # nothing old yet
    with app.state.lock:
        assert app.state.conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 20
    assert app.state.prune_events(time.time() + 31 * 86400) > 0  # a month later the events are gone
    assert client.get("/v1/board", headers=yang).json()["tasks"] == []

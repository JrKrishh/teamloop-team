"""Lead, member, viewer: who can see what, and who can remove whom."""

import pytest
from fastapi.testclient import TestClient

from hub.app import create
from tests.test_team import TOKEN, fake_chat, golden, member

LEAD_KEY = "lead-key-of-teamloop-0123456789"


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("HUB_SECURE_COOKIE", "0")
    monkeypatch.setenv("HUB_LEAD_KEYS", f"teamloop:{LEAD_KEY}")
    return create(":memory:", chat=fake_chat, start_worker=False)


def browser(app, token):
    c = TestClient(app)
    r = c.post("/v1/board/login", json={"room": "teamloop", "token": token})
    return c, r


def test_lead_key_signs_in_as_lead_and_room_token_as_member(app):
    agent = TestClient(app)
    member(agent, "yang")  # creates the room
    lead, r = browser(app, LEAD_KEY)
    assert r.json()["role"] == "lead" and lead.get("/v1/me").json()["role"] == "lead"
    mate, r = browser(app, TOKEN)
    assert r.json()["role"] == "member" and mate.get("/v1/me").json()["role"] == "member"
    assert browser(app, "wrong")[1].status_code == 403


def test_members_see_the_board_but_not_admin(app):
    agent = TestClient(app)
    yang = member(agent, "yang")
    agent.post("/v1/events", json={"events": golden("real_fix_add_done.json")}, headers=yang)
    mate, _ = browser(app, TOKEN)
    assert mate.get("/v1/board").json()["tasks"][0]["task"] == "T-3"  # teammates see each other's work
    assert mate.get("/v1/team").json()["role"] == "member"
    assert mate.get("/v1/settings").status_code == 403
    assert mate.delete("/v1/members/yang").status_code == 403
    assert agent.get("/v1/settings", headers=yang).status_code == 403  # a connector session is a member too


def test_lead_removes_a_member(app):
    agent = TestClient(app)
    sourabh = member(agent, "sourabh")
    lead, _ = browser(app, LEAD_KEY)
    assert lead.delete("/v1/members/sourabh").json() == {"ok": True, "removed": "sourabh"}
    # the old session is gone, the old identity key no longer works, history stays
    assert agent.post("/v1/events", json={"events": golden("real_fix_add_done.json")}, headers=sourabh).status_code == 401
    r = agent.post("/v1/join", json={"room": "teamloop", "display_name": "sourabh", "identity_key": "key-of-sourabh".ljust(24, "x")},
                   headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 409
    assert lead.delete("/v1/members/nobody").status_code == 404
    # restore frees the name; they rejoin and can post again
    assert lead.post("/v1/members/sourabh/restore").json()["restored"] == "sourabh"
    again = member(agent, "sourabh")
    assert agent.post("/v1/events", json={"events": golden("synthetic_blocked_migration.json")}, headers=again).status_code == 200


def test_removed_flag_in_team_view(app):
    agent = TestClient(app)
    s = member(agent, "sourabh")
    agent.post("/v1/events", json={"events": golden("synthetic_blocked_migration.json")}, headers=s)
    lead, _ = browser(app, LEAD_KEY)
    lead.delete("/v1/members/sourabh")
    team = lead.get("/v1/team").json()
    assert team["role"] == "lead" and team["members"][0]["removed"] is True


def test_settings_for_the_lead(app, monkeypatch):
    monkeypatch.setenv("HUB_GITHUB_REPOS", "JrKrishh/teamloop-team=teamloop,other/repo=elsewhere")
    member(TestClient(app), "yang")
    lead, _ = browser(app, LEAD_KEY)
    s = lead.get("/v1/settings").json()
    assert s["lead_key_set"] is True and s["github_repos"] == ["JrKrishh/teamloop-team"] and s["notify_webhook_set"] is False


def test_without_a_lead_key_the_token_holder_leads(monkeypatch):
    monkeypatch.setenv("HUB_SECURE_COOKIE", "0")
    monkeypatch.delenv("HUB_LEAD_KEYS", raising=False)
    app = create(":memory:", chat=fake_chat, start_worker=False)
    member(TestClient(app), "yang")
    _, r = browser(app, TOKEN)
    assert r.json()["role"] == "lead"


def test_demo_visitors_are_viewers(monkeypatch):
    monkeypatch.setenv("HUB_DEMO_ROOM", "demo")
    c = TestClient(create(":memory:", chat=fake_chat, start_worker=False))
    assert c.get("/v1/me").json() == {"room": "demo", "role": "viewer", "name": None, "demo": True}
    assert c.get("/v1/settings").status_code == 403 and c.delete("/v1/members/x").status_code == 403


def test_forged_role_in_cookie_is_rejected(app):
    member(TestClient(app), "yang")
    mate, _ = browser(app, TOKEN)
    cookie = mate.cookies.get("teamloop_board")
    room, role, expires, mac = cookie.split("|")
    forged = TestClient(app)
    forged.cookies.set("teamloop_board", f"{room}|lead|{expires}|{mac}")
    assert forged.get("/v1/settings").status_code == 401  # not lead, and not even a valid sign-in

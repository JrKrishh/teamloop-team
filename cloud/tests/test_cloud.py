"""The cloud hub end to end against real Postgres: sign-in, teams, invites, `teamloop login`, events, board."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from cloud import auth
from cloud.app import create
from tests.conftest import person

GOLDEN = Path(__file__).parents[2] / "agent_s" / "golden"
calls: list[str] = []


def golden(name):
    return json.loads((GOLDEN / name).read_text(encoding="utf-8"))["events"]


def fake_chat(job, messages, schema):
    calls.append(job)
    if job == "qa":
        return {"answerable": True, "answer": "T-3 is done (e1).", "citations": ["e1"], "unknowns": []}
    if job == "digest":
        return {"headline": "One fix shipped.", "shipped": [{"text": "T-3 add() fixed", "evidence": ["e1"]}],
                "in_progress": [], "blocked": [], "at_risk": []}
    return {"done": [{"text": "fixed add()", "evidence": ["e3"]}], "doing": [], "next": [], "blockers": [],
            "percent": 95, "confidence": "high"}


@pytest.fixture
def app(env):
    calls.clear()
    return create(chat=fake_chat)


def signin(app, name):
    c = TestClient(app)
    r = c.post("/v1/session", json={"access_token": f"access-token-{name}"})
    assert r.status_code == 200, r.text
    return c


def new_team(lead, name="Loopers"):
    r = lead.post("/v1/teams", json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def join(app, lead, team, name, role="member"):
    url = lead.post(f"/v1/teams/{team}/invites", json={"role": role}).json()["url"]
    c = signin(app, name)
    r = c.post(f"/v1/invites/{url.rsplit('/', 1)[1]}/accept")
    assert r.status_code == 200, r.text
    return c


def connect(app, browser, team):
    """`teamloop login`: start a device code, approve it in the browser, claim the connector token once."""
    cli = TestClient(app)
    start = cli.post("/v1/device/start", json={"label": "laptop"}).json()
    assert cli.get("/v1/device/poll", params={"device_code": start["device_code"]}).json() == {"status": "pending"}
    assert browser.get(f"/v1/device/{start['user_code']}").json() == {"valid": True}
    assert browser.post("/v1/device/approve", json={"user_code": start["user_code"], "team": team}).status_code == 200
    got = cli.get("/v1/device/poll", params={"device_code": start["device_code"]}).json()
    assert got["status"] == "approved" and got["token"].startswith("tl_") and got["team"]["id"] == team
    assert cli.get("/v1/device/poll", params={"device_code": start["device_code"]}).json() == {"status": "claimed"}
    return {"Authorization": f"Bearer {got['token']}"}


def age_events(url, seconds=120):
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("update events set received_at = received_at - make_interval(secs => %s)", (seconds,))


def test_signed_out_visitors_get_the_demo(app):
    c = TestClient(app)
    assert c.get("/v1/config").json()["mode"] == "cloud"
    assert c.get("/v1/me").json() == {"user": None, "role": "viewer", "demo": True, "teams": []}
    board = c.get("/v1/board").json()
    assert board["demo"] and board["tasks"] and board["role"] == "viewer"
    assert c.get(f"/v1/tasks/{board['tasks'][0]['task']}").json()["timeline"]
    assert c.get("/v1/team").json()["members"]
    assert c.post("/v1/teams", json={"name": "x"}).status_code == 401
    assert c.get("/v1/board", params={"team": "00000000-0000-0000-0000-000000000000"}).status_code == 401
    for page in ("/", "/auth", "/device", "/join/abc"):
        assert c.get(page).status_code == 200


def test_sign_in_create_team_sign_out(app):
    c = TestClient(app)
    assert c.post("/v1/session", json={"access_token": "not-a-supabase-token"}).status_code == 401
    yang = signin(app, "yang")
    assert yang.get("/v1/me").json()["teams"] == []
    team = new_team(yang)
    me = yang.get("/v1/me").json()
    assert me["user"]["name"] == "yang" and me["teams"] == [{"id": team, "name": "Loopers", "role": "lead"}]
    assert yang.get("/v1/board", params={"team": team}).json()["tasks"] == []
    assert yang.post("/v1/logout").json() == {"ok": True}
    assert yang.get("/v1/me").json()["user"] is None


def test_invite_link_brings_a_teammate_in_once(app):
    yang = signin(app, "yang")
    team = new_team(yang)
    url = yang.post(f"/v1/teams/{team}/invites", json={}).json()["url"]
    assert url.startswith("http://testserver/join/inv_")
    tok = url.rsplit("/", 1)[1]
    assert TestClient(app).get(f"/v1/invites/{tok}").json() == {"valid": True, "team": "Loopers", "team_id": team, "role": "member"}
    assert TestClient(app).post(f"/v1/invites/{tok}/accept").status_code == 401  # sign in first
    sourabh = signin(app, "sourabh")
    assert sourabh.get("/v1/board", params={"team": team}).status_code == 403  # not in the team yet
    assert sourabh.post(f"/v1/invites/{tok}/accept").json()["role"] == "member"
    sourabh.post(f"/v1/invites/{tok}/accept")  # a second click doesn't use the link up again
    assert sourabh.get("/v1/board", params={"team": team}).json()["role"] == "member"
    assert sourabh.post(f"/v1/teams/{team}/invites", json={}).status_code == 403  # members don't invite
    assert sourabh.get("/v1/settings", params={"team": team}).status_code == 403
    assert yang.get("/v1/settings", params={"team": team}).json()["members"] == 2
    assert TestClient(app).get("/v1/invites/inv_nope").json()["valid"] is False
    with psycopg.connect(app_db(), autocommit=True) as conn:
        assert conn.execute("select uses from invites").fetchone()[0] == 1


def app_db():
    import os

    return os.environ["DATABASE_URL"]


def test_teamloop_login_then_events_reach_the_board(app):
    yang = signin(app, "yang")
    team = new_team(yang)
    headers = connect(app, yang, team)
    agent = TestClient(app)
    assert agent.get("/v1/me", headers=headers).json()["team"] == {"id": team, "name": "Loopers", "role": "lead"}
    events = golden("real_fix_add_done.json")
    r = agent.post("/v1/events", json={"events": events}, headers=headers)
    assert r.json() == {"accepted": len(events), "duplicates": 0}
    assert agent.post("/v1/events", json={"events": events}, headers=headers).json()["duplicates"] == len(events)
    assert agent.post("/v1/events", json={"events": [{**events[0], "local": "secret"}]}, headers=headers).status_code == 400
    assert agent.post("/v1/events", json={"events": events}).status_code == 401
    assert yang.post("/v1/events", json={"events": events}).status_code == 401  # a browser session can't post events
    [card] = yang.get("/v1/board", params={"team": team}).json()["tasks"]
    assert card["task"] == "T-3" and card["members"] == ["yang"] and card["progress"] is None  # too fresh to estimate
    detail = yang.get("/v1/tasks/T-3", params={"team": team}).json()
    assert detail["timeline"] and detail["history"] == []
    view = yang.get("/v1/team", params={"team": team}).json()
    assert view["members"][0]["name"] == "yang" and view["members"][0]["tools"] == ["claude_code"]
    assert view["members"][0]["email"] == "yang@example.com"  # leads see emails


def test_member_names_come_from_the_account_not_the_event(app):
    yang = signin(app, "yang")
    team = new_team(yang)
    headers = connect(app, yang, team)
    events = [{**e, "member": "someone-else"} for e in golden("real_fix_add_done.json")]
    TestClient(app).post("/v1/events", json={"events": events}, headers=headers)
    assert yang.get("/v1/board", params={"team": team}).json()["tasks"][0]["members"] == ["yang"]


def test_agent_s_estimates_stale_tasks_once_on_board_read(app, env):
    yang = signin(app, "yang")
    team = new_team(yang)
    TestClient(app).post("/v1/events", json={"events": golden("real_fix_add_done.json")}, headers=connect(app, yang, team))
    assert yang.post("/v1/refresh", params={"team": team}).json() == {"updated": 0} and calls == []  # too fresh: still debouncing
    age_events(env)
    assert yang.get("/v1/board", params={"team": team}).json()["tasks"][0]["progress"] is None  # reads never wait on Agent S
    assert yang.post("/v1/refresh", params={"team": team}).json() == {"updated": 1}
    [card] = yang.get("/v1/board", params={"team": team}).json()["tasks"]
    assert card["progress"]["percent"] == 95 and calls == ["progress"]
    assert yang.post("/v1/refresh", params={"team": team}).json() == {"updated": 0}
    assert calls == ["progress"]  # nothing new since the snapshot: no second call
    assert TestClient(app).post("/v1/refresh").json() == {"updated": 0}  # the demo is precomputed
    assert yang.get("/v1/tasks/T-3", params={"team": team}).json()["history"][0]["percent"] == 95


def test_ask_and_digest(app):
    yang = signin(app, "yang")
    team = new_team(yang)
    TestClient(app).post("/v1/events", json={"events": golden("real_fix_add_done.json")}, headers=connect(app, yang, team))
    r = yang.post("/v1/ask", params={"team": team}, json={"question": "what's done?"}).json()
    assert r["answer"] == "T-3 is done." and r["citations"]
    first = yang.get("/v1/digest", params={"team": team}).json()
    assert first["shipped"][0]["text"] == "T-3 add() fixed"
    assert yang.get("/v1/digest", params={"team": team}).json() == first and calls.count("digest") == 1
    assert TestClient(app).post("/v1/ask", json={"question": "what's happening?"}).json()["answer"]  # the demo


def test_teams_dont_see_each_other(app):
    yang = signin(app, "yang")
    a = new_team(yang, "A")
    TestClient(app).post("/v1/events", json={"events": golden("real_fix_add_done.json")}, headers=connect(app, yang, a))
    other = signin(app, "other")
    b = new_team(other, "B")
    assert other.get("/v1/board", params={"team": b}).json()["tasks"] == []
    assert other.get("/v1/board", params={"team": a}).status_code == 403
    assert other.get("/v1/tasks/T-3", params={"team": a}).status_code == 403
    assert other.post("/v1/device/approve", json={"user_code": "BCDF-GHJK", "team": a}).status_code == 403
    assert other.get("/v1/board", params={"team": "not-a-uuid"}).status_code == 400


def test_lead_removes_and_restores_a_member(app):
    yang = signin(app, "yang")
    team = new_team(yang)
    sourabh = join(app, yang, team, "sourabh")
    headers = connect(app, sourabh, team)
    sid = person("sourabh").id
    assert sourabh.delete(f"/v1/teams/{team}/members/{person('yang').id}").status_code == 403
    assert yang.delete(f"/v1/teams/{team}/members/{person('yang').id}").status_code == 400  # not yourself
    assert yang.delete(f"/v1/teams/{team}/members/{sid}").json() == {"ok": True}
    assert TestClient(app).post("/v1/events", json={"events": golden("real_fix_add_done.json")}, headers=headers).status_code == 401
    assert sourabh.get("/v1/board", params={"team": team}).status_code == 403
    assert sourabh.get("/v1/me").json()["teams"] == []
    url = yang.post(f"/v1/teams/{team}/invites", json={}).json()["url"]
    assert sourabh.post(f"/v1/invites/{url.rsplit('/', 1)[1]}/accept").status_code == 403  # a link can't undo a removal
    removed = [m for m in yang.get("/v1/team", params={"team": team}).json()["members"] if m["removed"]]
    assert [m["name"] for m in removed] == ["sourabh"]
    assert yang.post(f"/v1/teams/{team}/members/{sid}/restore").json() == {"ok": True}
    assert sourabh.get("/v1/board", params={"team": team}).status_code == 200
    # the old connector token stays revoked: they run `teamloop login` again
    assert TestClient(app).post("/v1/events", json={"events": golden("real_fix_add_done.json")}, headers=headers).status_code == 401


def test_device_codes_expire_and_are_single_use(app, env):
    yang = signin(app, "yang")
    team = new_team(yang)
    start = TestClient(app).post("/v1/device/start", json={}).json()
    with psycopg.connect(env, autocommit=True) as conn:
        conn.execute("update devices set expires_at = now() - interval '1 second'")
    assert TestClient(app).get("/v1/device/poll", params={"device_code": start["device_code"]}).json() == {"status": "expired"}
    assert yang.post("/v1/device/approve", json={"user_code": start["user_code"], "team": team}).status_code == 404
    assert yang.get(f"/v1/device/{start['user_code']}").json() == {"valid": False}
    assert TestClient(app).get("/v1/device/poll", params={"device_code": "nope"}).status_code == 404


def test_supabase_user_reads_the_auth_server(monkeypatch):
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            seen.update(path=self.path, apikey=self.headers["apikey"], auth=self.headers["Authorization"])
            users = {"Bearer good": {"id": "u1", "email": "yang@example.com", "user_metadata": {"full_name": "Yang R"}},
                     # a GitHub account without a display name
                     "Bearer github": {"id": "u2", "email": "y@example.com", "user_metadata": {"user_name": "JrKrishh"}}}
            ok = self.headers["Authorization"] in users
            body = json.dumps(users.get(self.headers["Authorization"], {}))
            self.send_response(200 if ok else 401)
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("SUPABASE_URL", f"http://127.0.0.1:{srv.server_port}/")
        monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")
        assert auth.supabase_user("good") == auth.Person("u1", "yang@example.com", "Yang R")
        assert seen == {"path": "/auth/v1/user", "apikey": "sb_publishable_test", "auth": "Bearer good"}
        assert auth.supabase_user("github").name == "JrKrishh"
        with pytest.raises(PermissionError):
            auth.supabase_user("bad")
    finally:
        srv.shutdown()


def test_old_events_are_swept_after_retention(app, env, monkeypatch):
    import cloud.app

    yang = signin(app, "yang")
    team = new_team(yang)
    headers = connect(app, yang, team)
    TestClient(app).post("/v1/events", json={"events": golden("real_fix_add_done.json")}, headers=headers)
    age_events(env, 31 * 86400)
    monkeypatch.setattr(cloud.app.secrets, "randbelow", lambda n: 0)
    fresh = golden("real_codex_multiply_done.json")
    TestClient(app).post("/v1/events", json={"events": fresh}, headers=headers)
    assert [t["task"] for t in yang.get("/v1/board", params={"team": team}).json()["tasks"]] == ["T-7"]


def test_the_demo_needs_no_database(app, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none?connect_timeout=1")  # unreachable
    c = TestClient(app)
    assert c.get("/v1/me").json()["user"] is None
    board = c.get("/v1/board").json()
    assert board["demo"] and board["tasks"]
    assert c.get("/v1/team").json()["members"] and c.get("/v1/config").json()["mode"] == "cloud"

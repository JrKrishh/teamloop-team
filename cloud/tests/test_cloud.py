"""The cloud hub end to end against real Postgres: sign-in, teams, invites, `teamloop login`, events, board."""

import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from agent_s import llm
from cloud import auth
from cloud.app import create
from tests.conftest import person

GOLDEN = Path(__file__).parents[2] / "agent_s" / "golden"
calls: list[str] = []
AGENT_SEEN: list = []
AGENT_REPLY: dict = {}


def golden(name):
    return json.loads((GOLDEN / name).read_text(encoding="utf-8"))["events"]


def fake_chat(job, messages, schema):
    calls.append(job)
    if job == "qa":
        return {"answerable": True, "answer": "T-3 is done (e1).", "citations": ["e1"], "unknowns": []}
    if job == "agent":
        AGENT_SEEN.append(llm._pinned.get())
        return AGENT_REPLY
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
    landing = c.get("/")
    assert landing.status_code == 200 and "Download for Windows" in landing.text  # the website is the landing page
    assert "Join a team" in c.get("/join/inv_abc").text and c.get("/site/app-board.webp").status_code == 200
    for page in ("/auth", "/device"):  # `teamloop login` from a terminal still signs in on the web
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


def app_signin(app, name):
    r = TestClient(app).post("/v1/app/session", json={"access_token": f"access-token-{name}"})
    assert r.status_code == 200, r.text
    assert r.json()["token"].startswith("s_") and "set-cookie" not in r.headers  # the app holds it, not a browser
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_the_desktop_app_signs_in_and_connects_its_laptop(app):
    h = app_signin(app, "yang")
    c = TestClient(app)
    assert c.get("/v1/me", headers=h).json()["user"]["name"] == "yang"
    team = c.post("/v1/teams", json={"name": "Loopers"}, headers=h).json()["id"]
    link = c.post(f"/v1/teams/{team}/connector", json={"label": "yang-laptop"}, headers=h).json()
    assert link["token"].startswith("tl_") and link["team"] == {"id": team, "name": "Loopers"}
    assert link["name"] == "yang" and link["url"] == "http://testserver"
    agent = {"Authorization": f"Bearer {link['token']}"}
    events = golden("real_fix_add_done.json")
    assert c.post("/v1/events", json={"events": events}, headers=agent).json()["accepted"] == len(events)
    assert c.get("/v1/board", params={"team": team}, headers=h).json()["tasks"][0]["task"] == "T-3"
    assert c.post(f"/v1/teams/{team}/connector", json={}, headers=agent).status_code == 401  # tokens don't mint tokens
    assert c.post(f"/v1/teams/{team}/connector", json={}, headers=app_signin(app, "stranger")).status_code == 403
    assert c.post("/v1/logout", headers=h).json() == {"ok": True}
    assert c.get("/v1/me", headers=h).json()["user"] is None


def test_citations_expand_to_their_events(app):
    h = app_signin(app, "yang")
    c = TestClient(app)
    team = c.post("/v1/teams", json={"name": "Loopers"}, headers=h).json()["id"]
    events = golden("real_fix_add_done.json")
    link = c.post(f"/v1/teams/{team}/connector", json={}, headers=h).json()
    c.post("/v1/events", json={"events": events}, headers={"Authorization": f"Bearer {link['token']}"})
    wanted = [events[i]["id"] for i in (0, 3, 4)]  # events with a description line, as Agent S cites them
    got = c.get("/v1/events", params={"team": team, "ids": ",".join(wanted + ["not-an-id"])}, headers=h).json()["events"]
    assert {e["id"] for e in got} == set(wanted) and [e["ts"] for e in got] == sorted(e["ts"] for e in got)
    assert all(e["line"] and e["task"] in ("T-3", None) for e in got)
    assert c.get("/v1/events", params={"team": team, "ids": ",".join(wanted)}).status_code == 401
    demo_ids = [r["id"] for r in c.get("/v1/board").json()["tasks"][0]["recent"][:2]]
    assert [e["id"] for e in c.get("/v1/events", params={"ids": ",".join(demo_ids)}).json()["events"]] == demo_ids


def test_planned_tasks_show_on_the_board_until_sessions_take_over(app):
    yang = signin(app, "yang")
    team = new_team(yang)
    join(app, yang, team, "asha")
    q = {"team": team}
    t = yang.post("/v1/tasks", params=q, json={"title": "Build the OAuth callback", "owner": "ASHA"}).json()
    assert t == {"task": "T-1", "title": "Build the OAuth callback", "owner": "asha", "state": "open"}
    assert yang.post("/v1/tasks", params=q, json={"task": "T-1", "title": "Rate limits"}).json()["task"] == "T-2"  # taken
    assert yang.post("/v1/tasks", params=q, json={"title": "x", "owner": "a stranger"}).status_code == 400
    cards = {c["task"]: c for c in yang.get("/v1/board", params=q).json()["tasks"]}
    assert cards["T-1"]["status"] == "todo" and cards["T-1"]["owner"] == "asha" and cards["T-1"]["members"] == ["asha"]
    assert yang.get("/v1/tasks/T-1", params=q).json()["timeline"] == []
    assert yang.patch("/v1/tasks/T-2", params=q, json={"owner": "yang"}).json()["owner"] == "yang"
    assert yang.patch("/v1/tasks/T-2", params=q, json={"state": "closed"}).json() == {"task": "T-2", "title": "Rate limits", "owner": "yang", "state": "closed"}
    assert "T-2" not in {c["task"] for c in yang.get("/v1/board", params=q).json()["tasks"]}  # closed before any session
    assert yang.delete("/v1/tasks/T-1", params=q).json() == {"ok": True}  # undo
    assert yang.delete("/v1/tasks/T-1", params=q).status_code == 404
    # a task that only has session events can be assigned and closed too
    TestClient(app).post("/v1/events", json={"events": golden("real_fix_add_done.json")}, headers=connect(app, yang, team))
    assert yang.patch("/v1/tasks/T-3", params=q, json={"owner": "asha"}).json()["title"]  # keeps the session's title
    card = next(c for c in yang.get("/v1/board", params=q).json()["tasks"] if c["task"] == "T-3")
    assert card["owner"] == "asha" and card["events"] > 0
    yang.patch("/v1/tasks/T-3", params=q, json={"state": "closed"})
    assert next(c for c in yang.get("/v1/board", params=q).json()["tasks"] if c["task"] == "T-3")["status"] == "done"
    assert yang.patch("/v1/tasks/T-9", params=q, json={"state": "closed"}).status_code == 404
    assert signin(app, "stranger").post("/v1/tasks", params=q, json={"title": "x"}).status_code == 403


def test_agent_turns_plan_and_route_models(app):
    global AGENT_REPLY
    yang = signin(app, "yang")
    team = new_team(yang)
    join(app, yang, team, "asha")
    q = {"team": team}
    AGENT_REPLY = {"kind": "plan", "answer": "Two tasks from your spec.", "citations": [], "plan": ["Create", "Assign"],
                   "actions": [{"type": "create_task", "task": "", "title": "OAuth callback", "owner": "asha", "why": "item 1"},
                               {"type": "assign_task", "task": "T-404", "title": "", "owner": "asha", "why": "not on the board"}]}
    AGENT_SEEN.clear()
    spec = [{"name": "spec.md", "text": "- OAuth callback"}]
    resp = yang.post("/v1/agent", params=q, json={"message": "plan this", "mode": "plan", "attachments": spec})
    assert resp.status_code == 200, resp.text
    r = resp.json()
    assert r["plan"] == ["Create", "Assign"] and r["mode"] == "plan"
    assert [(a["type"], a["task"], a["owner"]) for a in r["actions"]] == [("create_task", "T-1", "asha")]
    yang.post("/v1/agent", params=q, json={"message": "what's up", "mode": "manual"})
    yang.post("/v1/agent", params=q, json={"message": "what's up", "mode": "auto", "model": "lightning"})
    assert AGENT_SEEN == ["ultra", None, "lightning"]  # Auto: Ultra for plans and imports; the picker pins a tier
    assert yang.post("/v1/agent", params=q, json={"message": "x", "model": "gpt-9"}).status_code == 422
    assert TestClient(app).post("/v1/agent", params=q, json={"message": "x"}).status_code == 401
    assert signin(app, "stranger").post("/v1/agent", params=q, json={"message": "x"}).status_code == 403


def test_llm_steps_for_the_app_agent_loop(env):
    seen = []

    def step(messages, tools, max_tokens):
        seen.append((llm._pinned.get(), len(messages), [t["function"]["name"] for t in tools], max_tokens))
        if messages[-1]["content"] == "boom":
            raise RuntimeError("model down")
        return {"content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "team_board", "arguments": "{}"}}],
                "model": "nebius:nvidia/nemotron-3-super-120b-a12b"}

    app = create(chat=fake_chat, chat_step=step)
    h = app_signin(app, "yang")
    c = TestClient(app)
    tools = [{"type": "function", "function": {"name": "team_board", "description": "x", "parameters": {"type": "object", "properties": {}}}}]
    r = c.post("/v1/llm", headers=h, json={"tier": "ultra", "messages": [{"role": "user", "content": "hi"}], "tools": tools, "max_tokens": 900})
    assert r.status_code == 200 and r.json()["tool_calls"][0]["function"]["name"] == "team_board"
    assert seen == [("ultra", 1, ["team_board"], 900)]
    assert c.post("/v1/llm", json={"messages": [{"role": "user", "content": "hi"}]}).status_code == 401
    assert c.post("/v1/llm", headers=h, json={"messages": [{"role": "user", "content": "x" * 410_000}]}).status_code == 413
    assert c.post("/v1/llm", headers=h, json={"messages": [{"role": "user", "content": "boom"}]}).status_code == 503
    assert c.post("/v1/llm", headers=h, json={"tier": "gpt-9", "messages": [{"role": "user", "content": "hi"}]}).status_code == 422


def turn(n, task, usage, tool="claude_code", session="s1", at=None):
    ts = (at or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return {"v": 1, "id": f"{n:032x}", "ts": ts, "tool": tool, "session": session, "kind": "turn_end", "task": task,
            "facts": {"usage": usage}}


def test_usage_counts_tokens_by_task_tool_day_and_person(env):
    def step(messages, tools, max_tokens):
        return {"content": "ok", "tool_calls": [], "model": "nebius:nvidia/nemotron-3-super-120b-a12b", "usage": {"in": 1000, "out": 200}}

    def chat(job, messages, schema):  # Agent S's own calls count through llm.meter()
        llm._count("nvidia/nemotron-3-super-120b-a12b", {"usage": {"prompt_tokens": 300, "completion_tokens": 50}})
        return fake_chat(job, messages, schema)

    app = create(chat=chat, chat_step=step)
    yang = signin(app, "yang")
    team = new_team(yang)
    asha = join(app, yang, team, "asha")
    now = datetime.now(timezone.utc)
    opus = {"model": "claude-opus-5-5", "in": 10, "cw": 1000, "cr": 50_000, "out": 500, "calls": 3}
    luna = {"model": "gpt-5.6-luna", "in": 2000, "cw": 0, "cr": 9000, "out": 300, "calls": 2}
    mine = [turn(1, "T-3", opus, at=now), turn(2, "T-3", opus, at=now - timedelta(days=1)),
            {"v": 1, "id": f"{3:032x}", "ts": turn(0, None, {})["ts"], "tool": "claude_code", "kind": "tool", "facts": {"tool": "Bash"}}]
    TestClient(app).post("/v1/events", json={"events": mine}, headers=connect(app, yang, team))
    TestClient(app).post("/v1/events", json={"events": [turn(4, "T-4", luna, tool="codex", session="s2", at=now)]},
                         headers=connect(app, asha, team))
    msg = {"messages": [{"role": "user", "content": "hi"}]}
    assert yang.post("/v1/llm", params={"team": team}, json=msg).status_code == 200  # counts for the team
    assert yang.post("/v1/llm", json=msg).status_code == 200  # no team named: not counted anywhere
    assert asha.post("/v1/ask", params={"team": team}, json={"question": "what's done?"}).status_code == 200

    lead = yang.get("/v1/usage", params={"team": team, "days": 7, "tz": 330}).json()
    assert lead["coding"]["tokens"] == 2 * 1510 + 2300 and lead["coding"]["cr"] == 2 * 50_000 + 9000
    assert lead["coding"]["turns"] == 3 and lead["coding"]["sessions"] == 2 and lead["tools"]["codex"]["tokens"] == 2300
    assert lead["agents"]["tokens"] == 1200 + 350 and lead["agents"]["calls"] == 2
    assert lead["agents"]["sources"] == {"app": 1200, "ask": 350} and lead["total"] == 2 * 1510 + 2300 + 1550
    assert [(t["task"], t["tokens"], t["people"]) for t in lead["tasks"]] == [("T-3", 3020, ["yang"]), ("T-4", 2300, ["asha"])]
    assert lead["by_day"][-1]["day"] == lead["today"] and lead["by_day"][-1]["claude_code"] == 1510
    assert lead["by_day"][-2]["claude_code"] == 1510 and lead["by_day"][-1]["codex"] == 2300 and len(lead["by_day"]) == 7
    assert lead["scope"] == "team" and [(p["name"], p["total"]) for p in lead["people"]] == [("asha", 2300 + 350), ("yang", 3020 + 1200)]
    member = asha.get("/v1/usage", params={"team": team}).json()  # a member sees the team's totals and only their own row
    assert member["scope"] == "you" and [p["name"] for p in member["people"]] == ["asha"] and member["total"] == lead["total"]
    cards = {c["task"]: c for c in yang.get("/v1/board", params={"team": team}).json()["tasks"]}
    assert cards["T-3"]["usage"] == {"tokens": 3020, "turns": 2} and cards["T-4"]["usage"]["tokens"] == 2300
    assert yang.get("/v1/tasks/T-3", params={"team": team}).json()["usage"]["turns"] == 2
    assert signin(app, "other").get("/v1/usage", params={"team": team}).status_code == 403

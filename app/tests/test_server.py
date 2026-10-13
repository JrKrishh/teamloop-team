"""The app's local server: the guard, both sign-ins, the hub proxy and this laptop's setup. The hub and Supabase are
stand-ins; the connector code (init, config, spool) is real, in a throwaway home and repo."""

import json
import subprocess
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from superagents import server, store, supa
from teamloop import claude, codex, send, spool

PORT = 47123
TEAM = "11111111-2222-3333-4444-555555555555"


class Hub:
    """Stand-in for the cloud hub: records calls, answers the few the app makes."""

    def __init__(self):
        self.calls = []
        self.user = {"id": "u-yang", "email": "yang@example.com", "name": "Yang"}

    def __call__(self, state, method, path, body=None, query=None, token=None):
        tok = store.load().get("session") if token is None else token
        self.calls.append((method, path, body, query, tok))
        if path == "/v1/config":
            return 200, {"mode": "cloud", "supabase_url": "https://sb.example", "supabase_key": "sb_publishable_x"}
        if path == "/v1/app/session":
            return 200, {"token": "s_session", "user": self.user}
        if path == "/v1/me":
            if tok != "s_session":
                return 200, {"user": None, "teams": []}
            return 200, {"user": self.user, "teams": [{"id": TEAM, "name": "Loopers", "role": "lead"}]}
        if path == f"/v1/teams/{TEAM}/connector":
            return 200, {"token": "tl_laptop", "team": {"id": TEAM, "name": "Loopers"}, "name": "Yang"}
        if path == "/v1/board":
            return 200, {"room": "Loopers", "tasks": [], "query": query}
        if path == "/v1/logout":
            return 200, {"ok": True}
        return 404, {"detail": "no"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("TEAMLOOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HOME", str(tmp_path / "userhome"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "userhome"))
    monkeypatch.setattr(claude, "register_mcp", lambda cwd, scope: "registered (test)")
    monkeypatch.setattr(codex, "cli", lambda: None)
    hub = Hub()
    monkeypatch.setattr(server, "cloud", hub)
    opened = []
    state = server.State("https://hub.example", port=PORT, key="the-key")
    app = server.create(state, open_url=opened.append)
    client = TestClient(app, base_url=f"http://127.0.0.1:{PORT}")
    client.headers["X-App-Key"] = "the-key"
    return client, hub, state, opened


def test_guard(env):
    client, *_ = env
    assert client.get("/api/boot").status_code == 200
    assert client.get("/api/boot", headers={"X-App-Key": "wrong"}).status_code == 403
    assert TestClient(client.app, base_url="http://evil.example").get("/").status_code == 403  # DNS rebinding
    bare = TestClient(client.app, base_url=f"http://127.0.0.1:{PORT}")
    assert bare.get("/").status_code == 200 and "Super Agents" in bare.get("/").text  # the page itself needs no key
    assert bare.get("/api/boot").status_code == 403


def test_github_sign_in_through_the_browser(env, monkeypatch):
    client, hub, state, opened = env
    assert client.get("/api/boot").json()["signed_in"] is False
    seen = {}

    def exchange(url, key, code, verifier):
        seen.update(url=url, key=key, code=code, verifier=verifier)
        return {"access_token": "sb-access", "user": {"email": "yang@example.com",
                                                      "user_metadata": {"user_name": "JrKrishh", "avatar_url": "https://avatars.example/y.png"}}}

    monkeypatch.setattr(supa, "exchange_code", exchange)
    url = client.post("/api/auth/github").json()["url"]
    assert opened == [url] and client.get("/api/auth/status").json() == {"state": "waiting"}
    q = parse_qs(urlparse(url).query)
    assert url.startswith("https://sb.example/auth/v1/authorize?") and q["provider"] == ["github"]
    assert q["code_challenge_method"] == ["s256"] and len(q["code_challenge"][0]) == 43
    back = urlparse(q["redirect_to"][0])
    assert f"{back.scheme}://{back.netloc}{back.path}" == f"http://127.0.0.1:{PORT}/auth/callback"
    flow = parse_qs(back.query)["flow"][0]

    page = TestClient(client.app, base_url=f"http://127.0.0.1:{PORT}").get(f"/auth/callback?flow={flow}&code=the-code")
    assert page.status_code == 200 and "signed in" in page.text
    assert seen["code"] == "the-code" and seen["key"] == "sb_publishable_x"
    assert ("POST", "/v1/app/session", {"access_token": "sb-access"}, None, "") in hub.calls  # no session sent along
    assert client.get("/api/auth/status").json() == {"state": "done"}
    boot = client.get("/api/boot").json()
    assert boot["signed_in"] and boot["user"]["avatar"] == "https://avatars.example/y.png" and boot["team"] == TEAM
    # the same link can't be used twice, and a forged one is refused
    again = TestClient(client.app, base_url=f"http://127.0.0.1:{PORT}").get(f"/auth/callback?flow={flow}&code=x")
    assert again.status_code == 400 and client.get("/api/auth/status").json()["state"] == "error"


def test_email_sign_in_and_sign_up(env, monkeypatch):
    client, hub, *_ = env
    monkeypatch.setattr(supa, "password", lambda *a: (_ for _ in ()).throw(supa.AuthError("Invalid login credentials")))
    r = client.post("/api/auth/email", json={"email": "yang@example.com", "password": "wrongwrong"})
    assert r.status_code == 401 and r.json()["detail"] == "Invalid login credentials"
    monkeypatch.setattr(supa, "signup", lambda *a: {"user": {"email": "yang@example.com"}})  # email confirmation on
    assert client.post("/api/auth/email", json={"email": "yang@example.com", "password": "rightright", "mode": "signup",
                                                "name": "Yang"}).json() == {"confirm": True}
    monkeypatch.setattr(supa, "password", lambda *a: {"access_token": "sb-access", "user": {"email": "yang@example.com"}})
    assert client.post("/api/auth/email", json={"email": "yang@example.com", "password": "rightright"}).json() == {"ok": True}
    assert client.get("/api/boot").json()["signed_in"]


def signed_in(monkeypatch, client):
    monkeypatch.setattr(supa, "password", lambda *a: {"access_token": "sb-access", "user": {"email": "yang@example.com"}})
    client.post("/api/auth/email", json={"email": "yang@example.com", "password": "rightright"})


def test_hub_calls_go_through_with_the_session_only_on_known_paths(env, monkeypatch):
    client, hub, *_ = env
    signed_in(monkeypatch, client)
    r = client.get("/api/cloud/board", params={"team": TEAM})
    assert r.status_code == 200 and r.json()["query"] == {"team": TEAM}
    assert hub.calls[-1][1:] == ("/v1/board", None, {"team": TEAM}, "s_session")
    assert client.get("/api/cloud/admin/everything").status_code == 404
    assert client.post(f"/api/cloud/teams/{TEAM}/connector").status_code == 404  # the laptop flow does that, not the UI


def test_connect_this_laptop_and_a_repo(env, monkeypatch, tmp_path):
    client, hub, *_ = env
    signed_in(monkeypatch, client)
    status = client.post("/api/laptop/team", json={"team": TEAM}).json()
    assert status["team"] == {"id": TEAM, "name": "Loopers"} and status["name"] == "Yang"
    assert send.config() == {"mode": "cloud", "url": "https://hub.example", "token": "tl_laptop", "name": "Yang",
                             "team": {"id": TEAM, "name": "Loopers"}}
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "T-5-thing"], cwd=root, check=True)
    r = client.post("/api/laptop/repos", json={"path": str(root)}).json()
    assert r["ok"] and r["repo"]["claude_code"] and r["repo"]["name"] == "proj" and "Claude Code hooks" in r["log"]
    assert [x["name"] for x in client.get("/api/laptop").json()["repos"]] == ["proj"]
    assert client.post("/api/laptop/repos", json={}).json() == {"cancelled": True}  # no folder picked
    assert client.post("/api/laptop/pause", json={"paused": True}).json()["paused"] and spool.paused()
    assert client.post("/api/laptop/pause", json={"paused": False}).json()["paused"] is False


def test_sign_out_stops_this_laptop_reporting(env, monkeypatch):
    client, hub, *_ = env
    signed_in(monkeypatch, client)
    client.post("/api/laptop/team", json={"team": TEAM})
    assert client.post("/api/auth/signout").json() == {"ok": True}
    assert ("POST", "/v1/logout", None, None, "s_session") in hub.calls
    assert send.config() is None and store.load() == {} and client.get("/api/boot").json()["signed_in"] is False


def test_someone_else_signing_in_disconnects_the_previous_person(env, monkeypatch):
    client, hub, *_ = env
    signed_in(monkeypatch, client)
    client.post("/api/laptop/team", json={"team": TEAM})
    client.post("/api/team", json={"team": TEAM})
    hub.user = {"id": "u-sourabh", "email": "s@example.com", "name": "Sourabh"}
    signed_in(monkeypatch, client)
    assert send.config() is None  # no longer reporting as Yang
    assert store.load().get("team") is None
    assert json.loads((spool.home() / "app.json").read_text())["user_id"] == "u-sourabh"

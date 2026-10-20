"""The app's local server: the guard, both sign-ins, the hub proxy and this laptop's setup. The hub and Supabase are
stand-ins; the connector code (init, config, spool) is real, in a throwaway home and repo."""

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from superagents import laptop, main, server, store, supa
from superagents.runtime import tools as runtime_tools
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
        if path == "/v1/tasks/T-3" and method == "PATCH":
            return 200, {"task": "T-3", "state": body.get("state")}
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


def test_this_laptop_says_which_of_teammates_agents_commits_it_lacks(env, monkeypatch, tmp_path):
    import subprocess

    client, hub, *_ = env
    root = tmp_path / "web"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "first"], cwd=root, check=True)
    have = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
    monkeypatch.setattr(server.store, "repos", lambda: [str(root)])
    pushes = [{"id": "e" * 32, "member": "Asha", "repo": "web", "branch": "main", "at": 1.0, "commits": [
        {"sha": "a" * 12, "subject": "Rename the session API", "task": "T-19", "files": []},
        {"sha": have[:12], "subject": "Already here", "task": "T-19", "files": []}]}]

    def cloud(state, method, path, body=None, query=None, token=None):
        return (200, {"repo": query["repo"], "pushes": pushes, "tasks": {}}) if path == "/v1/changes" else hub(state, method, path, body, query, token)
    monkeypatch.setattr(server, "cloud", cloud)
    got = client.get("/api/laptop/changes", params={"team": TEAM}).json()
    assert got == {"repos": [{"repo": "web", "lacking": 1, "from": ["Asha"], "tasks": ["T-19"]}]}
    r = client.post("/api/laptop/pull", json={"repo": "web"})  # no upstream here: said, not a crash
    assert r.status_code == 400 and r.json()["detail"]


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
    assert store.load()["team"] == TEAM  # the team shown is the one the phone gets, before anyone picks one
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
    git = client.get("/api/laptop/git").json()
    assert git["git"] is True and set(git["origins"]) == {str(root.resolve())}  # proj has no origin: ""


def test_get_the_project_clones_only_github_repos(env, monkeypatch, tmp_path):
    client, hub, *_ = env
    cloned = []
    monkeypatch.setattr(server.laptop, "clone", lambda url, parent: cloned.append((url, parent)) or {"ok": True, "path": parent})
    assert client.post("/api/laptop/clone", json={"url": "https://gitlab.com/acme/web"}).status_code == 400
    assert client.post("/api/laptop/clone", json={"url": "https://github.com/acme/web"}).json() == {"cancelled": True}
    assert client.post("/api/laptop/clone", json={"url": "git@github.com:acme/web.git", "parent": str(tmp_path)}).json()["ok"]
    assert cloned == [("https://github.com/acme/web.git", str(tmp_path))]
    client.get(f"/api/cloud/teams/{TEAM}/repos")
    assert hub.calls[-1][1] == f"/v1/teams/{TEAM}/repos"  # the UI may reach the team's repos


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


def test_task_changes_reach_the_hub(env, monkeypatch):
    client, hub, *_ = env
    signed_in(monkeypatch, client)
    assert client.patch("/api/cloud/tasks/T-3", params={"team": TEAM}, json={"state": "closed"}).json() == {"task": "T-3", "state": "closed"}
    assert hub.calls[-1][:2] == ("PATCH", "/v1/tasks/T-3")
    assert client.post("/api/cloud/agent", params={"team": TEAM}, json={}).status_code == 404  # agents run on this laptop now


def test_super_team_calls_reach_the_hub_but_running_prompts_stays_with_the_runner(env, monkeypatch):
    client, hub, *_ = env
    signed_in(monkeypatch, client)
    pid = "11111111-2222-3333-4444-555555555555"
    for method, path in [("GET", "sessions"), ("PUT", "sessions/access"), ("POST", "prompts"),
                         ("POST", f"prompts/{pid}/decide"), ("POST", f"prompts/{pid}/cancel"), ("GET", "messages"), ("POST", "messages"),
                         ("POST", "messages/read")]:
        r = client.request(method, f"/api/cloud/{path}", params={"team": TEAM}, json={"mode": "auto"} if method != "GET" else None)
        assert r.json().get("detail") != "Not a Super Agents call", path
    assert any(c[0] == "PUT" and c[1] == "/v1/sessions/access" and c[2] == {"mode": "auto"} for c in hub.calls)
    assert client.get("/api/cloud/me").json()["detail"] == "Not a Super Agents call"  # only what the page uses gets through
    for path in ("prompts/runnable", f"prompts/{pid}/claim", f"prompts/{pid}/finish"):  # only this laptop's runner does these
        assert client.post(f"/api/cloud/{path}", json={}).json()["detail"] == "Not a Super Agents call"


def test_start_task_on_this_laptop(env, monkeypatch, tmp_path):
    """The agents' start_task tool: this laptop's sessions report on a task, in the repo it names."""
    client, hub, *_ = env
    signed_in(monkeypatch, client)
    with pytest.raises(ValueError, match="connect one"):
        runtime_tools.start_task(None, "T-23", "OAuth")  # no repo yet
    repos = []
    for name in ("web", "api"):
        root = tmp_path / name
        root.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
        client.post("/api/laptop/repos", json={"path": str(root)})
        repos.append(root)
    with pytest.raises(ValueError, match="Say which repo: web, api"):
        runtime_tools.start_task(None, "T-23")  # two repos: which one?
    with pytest.raises(ValueError, match="isn't connected"):
        runtime_tools.start_task(None, "T-23", repo="mobile")
    with pytest.raises(ValueError, match="looks like T-23"):
        runtime_tools.start_task(None, "not a task", repo="web")
    assert runtime_tools.start_task(None, "T-23", "OAuth callback", repo="web") == "This laptop's sessions in web now report on T-23"
    got = subprocess.run(["git", "config", "teamloop.task"], cwd=repos[0], capture_output=True, text=True).stdout.strip()
    assert got == "T-23"
    started = [spool.read(p) for p in spool.pending()]
    assert any(e["kind"] == "task_start" and e["task"] == "T-23" and e["facts"] == {"title": "OAuth callback"} for e in started)


def test_import_github_issues(env, monkeypatch):
    client, *_ = env

    class Resp:
        def __init__(self, data):
            self.data = data

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(self.data).encode()

    seen = {}

    def fake_urlopen(req, timeout=0):
        seen["url"] = req.full_url
        return Resp([{"number": 12, "title": "OAuth callback", "labels": [{"name": "auth"}], "body": "Users sign in with GitHub"},
                     {"number": 13, "title": "a pull request", "pull_request": {}, "labels": [], "body": ""}])

    monkeypatch.setattr(server.urllib.request, "urlopen", fake_urlopen)
    r = client.get("/api/import/github", params={"repo": "https://github.com/acme/web/"}).json()
    assert seen["url"].startswith("https://api.github.com/repos/acme/web/issues?state=open")
    assert r["name"] == "acme/web issues (1)" and r["text"].startswith("#12 OAuth callback  [auth]") and "pull request" not in r["text"]
    assert client.get("/api/import/github", params={"repo": "not a repo"}).status_code == 400


def test_a_second_launch_shows_the_open_window(env):
    client, hub, state, opened = env
    shown = []
    app = server.create(state, show_window=lambda: shown.append(True))
    one = TestClient(app, base_url=f"http://127.0.0.1:{PORT}")
    assert one.post("/api/window/show").status_code == 403  # only with this copy's key
    assert one.post("/api/window/show", headers={"X-App-Key": "the-key"}).json() == {"ok": True} and shown == [True]


def test_connect_from_github_lists_repos_through_this_laptops_sign_in(env, monkeypatch):
    def repo(i, **more):
        return {"full_name": f"yang/r{i}", "html_url": f"https://github.com/yang/r{i}", "pushed_at": "2026-10-14T10:00:00Z", **more}
    monkeypatch.setattr(laptop.shutil, "which", lambda n: "gh" if n == "gh" else None)  # the GitHub CLI, signed in

    def gh(cmd, **kw):
        assert cmd[:2] == ["gh", "api"] and "affiliation=owner,collaborator,organization_member" in cmd[2]
        page = int(cmd[2].rsplit("page=", 1)[1])
        return SimpleNamespace(returncode=0, stdout=json.dumps([repo(i, private=i == 0) for i in range(100 if page == 1 else 3)]))
    r = laptop.github_repos(run=gh)
    assert r["via"] == "gh" and len(r["repos"]) == 103  # every page
    assert r["repos"][0] == {"name": "yang/r0", "url": "https://github.com/yang/r0", "private": True, "description": "", "pushed": "2026-10-14T10:00:00Z"}

    monkeypatch.setattr(laptop.shutil, "which", lambda n: None)  # no CLI: Git Credential Manager's token, for GitHub's API only
    asked = []

    def gcm(cmd, **kw):
        assert cmd == ["git", "credential", "fill"] and "host=github.com" in kw["input"] and kw["env"]["GCM_INTERACTIVE"] == "never"
        return SimpleNamespace(returncode=0, stdout="protocol=https\nhost=github.com\nusername=yang\npassword=gho_token\n")
    r = laptop.github_repos(run=gcm, fetch=lambda url, token: asked.append((url, token)) or [repo(7)])
    assert r == {"via": "git", "repos": [{"name": "yang/r7", "url": "https://github.com/yang/r7", "private": False, "description": "",
                                          "pushed": "2026-10-14T10:00:00Z"}]}
    assert asked == [("https://api.github.com/user/repos?per_page=100&sort=pushed&affiliation=owner,collaborator,organization_member&page=1", "gho_token")]

    with pytest.raises(LookupError):  # neither signed in
        laptop.github_repos(run=lambda cmd, **kw: SimpleNamespace(returncode=1, stdout=""))
    client, *_ = env
    monkeypatch.setattr(laptop, "github_repos", lambda: (_ for _ in ()).throw(LookupError("Sign in to GitHub on this laptop first")))
    got = client.get("/api/github/repos")
    assert got.status_code == 409 and got.json()["detail"].startswith("Sign in to GitHub")


def test_the_apps_own_title_bar(env):
    client, hub, state, opened = env
    assert client.get("/api/boot").json()["frame"] == "native"  # until frame.py has drawn its own
    state.frame = "custom"
    assert client.get("/api/boot").json()["frame"] == "custom"
    done = []
    app = server.create(state, window_action=done.append)
    buttons = TestClient(app, base_url=f"http://127.0.0.1:{PORT}")
    assert buttons.post("/api/window/close").status_code == 403  # only with this copy's key
    for name in ("minimize", "maximize", "close"):
        assert buttons.post(f"/api/window/{name}", headers={"X-App-Key": "the-key"}).json() == {"ok": True}
    assert done == ["minimize", "maximize", "close"]


@pytest.mark.skipif(sys.platform != "win32", reason="the one-copy lock is a Windows mutex")
def test_only_one_copy_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("TEAMLOOP_HOME", str(tmp_path / "home"))
    asked = []

    class Open(BaseHTTPRequestHandler):  # the copy that's already open
        def do_POST(self):
            asked.append((self.path, self.headers.get("X-App-Key")))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok": true}')

        def log_message(self, *a):
            pass

    first = HTTPServer(("127.0.0.1", 0), Open)
    threading.Thread(target=first.handle_request, daemon=True).start()
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "window.json").write_text(json.dumps({"port": first.server_port, "key": "k1", "pid": os.getpid()}))
    assert main._open_already() is False  # the first copy takes the lock
    assert main._open_already() is True  # a second launch finds it, and asks it to show its window
    assert asked == [("/api/window/show", "k1")]
    first.server_close()


def test_prefs_merge(env):
    client, *_ = env
    assert client.post("/api/prefs", json={"theme": "light"}).json() == {"theme": "light"}
    assert client.post("/api/prefs", json={"mode": "plan", "model": "ultra"}).json() == {"theme": "light", "mode": "plan", "model": "ultra"}
    assert client.get("/api/boot").json()["prefs"]["mode"] == "plan"
    assert client.post("/api/prefs", json={"model": "gpt-9"}).status_code == 422
    assert client.post("/api/prefs", json={"agent": "agent-1a2b3c"}).json()["agent"] == "agent-1a2b3c"
    assert client.post("/api/prefs", json={"agent": "../x"}).status_code == 422

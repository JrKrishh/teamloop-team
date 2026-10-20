"""Super Team → Files on the laptop: what's shared is read here (secrets refused) and uploaded straight to the storage
link; what's received is checked and saved only into a repo's inbox, out of git; branches are checked out cleanly."""

import base64
import hashlib
import subprocess
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from superagents import shares
from superagents.runtime import tools


class Storage(BaseHTTPRequestHandler):
    blobs: dict = {}

    def do_PUT(self):
        self.blobs[self.path] = self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        data = self.blobs.get(self.path)
        self.send_response(200 if data is not None else 404)
        self.end_headers()
        self.wfile.write(data or b"")

    def log_message(self, *a):
        pass


@pytest.fixture
def hub():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Storage)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base, made = f"http://127.0.0.1:{srv.server_port}", {}

    def call(method, path, body=None):
        if method == "POST" and path == "shares":
            sid = str(uuid.uuid4())
            made[sid] = {"id": sid, "kind": "files", "status": "uploading", "to": {"name": body["to"]} if body["to"] else None,
                         "note": body["note"], "files": [{"n": i, **f} for i, f in enumerate(body["files"])]}
            return {**made[sid], "uploads": [{"name": f["name"], "url": f"{base}/{sid}/{i}", "method": "PUT", "headers": {}}
                                             for i, f in enumerate(body["files"])]}
        sid = path.split("/")[1]
        if path.endswith("/ready"):
            assert all(f"/{sid}/{f['n']}" in Storage.blobs for f in made[sid]["files"])
            made[sid]["status"] = "ready"
            return made[sid]
        if "/files/" in path:
            f = made[sid]["files"][int(path.rsplit("/", 1)[1])]
            return {"url": f"{base}/{sid}/{f['n']}", "name": f["name"], "size": f["size"], "sha256": f["sha256"]}
        return made[sid]

    call.made, call.base = made, base
    yield call
    srv.shutdown()


def git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_sharing_reads_files_here_refuses_secrets_and_uploads_straight_to_storage(hub):
    s = shares.send(hub, [("docs/notes.md", b"# Notes\nship friday\n")], to="ravi", note="for the demo")
    assert s["status"] == "ready" and s["files"][0]["name"] == "notes.md" and s["to"] == {"name": "ravi"}
    assert Storage.blobs[f"/{s['id']}/0"] == b"# Notes\nship friday\n"
    with pytest.raises(PermissionError, match=r"^\.env\.local is a secrets file"):
        shares.send(hub, [("app/.env.local", b"X=1")])
    with pytest.raises(PermissionError, match="line 2"):
        shares.send(hub, [("config.txt", b"name = web\ntoken = sk_live_abcdef1234567890abcdef\n")])
    with pytest.raises(ValueError, match="over 25 MB"):
        shares.send(hub, [("big.bin", b"\0" * (shares.MAX_BYTES + 1))])
    assert len(hub.made) == 1  # nothing refused reached the hub


def test_received_files_go_only_into_the_repos_inbox_out_of_git(hub, tmp_path):
    repo = tmp_path / "web"
    repo.mkdir()
    git(repo, "init", "-q")
    data = b"stack trace\n"
    sid = str(uuid.uuid4())
    hub.made[sid] = {"id": sid, "kind": "files", "status": "ready", "files": [
        {"n": 0, "name": "..\\..\\evil.txt", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}]}
    Storage.blobs[f"/{sid}/0"] = data
    first = shares.save(hub, hub.made[sid], repo)
    again = shares.save(hub, hub.made[sid], repo)
    inbox = repo / ".superagents" / "inbox" / sid[:8]
    assert first == [inbox / "evil.txt"] and again == [inbox / "evil (2).txt"] and first[0].read_bytes() == data
    assert (repo / ".git" / "info" / "exclude").read_text().count("/.superagents/inbox/") == 1
    assert git(repo, "status", "--porcelain") == ""  # git doesn't see the inbox
    Storage.blobs[f"/{sid}/0"] = b"tampered\n"
    with pytest.raises(RuntimeError, match="intact"):
        shares.save(hub, hub.made[sid], repo)
    assert sorted(p.name for p in inbox.iterdir()) == ["evil (2).txt", "evil.txt"]


def test_a_branch_handed_over_is_checked_out_only_into_a_clean_repo(tmp_path, monkeypatch):
    (tmp_path / "gitconfig").write_text("[user]\n\tname = T\n\temail = t@example.com\n[init]\n\tdefaultBranch = main\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    git(tmp_path, "init", "--bare", "-q", "remote.git")
    git(tmp_path, "clone", "-q", "remote.git", "asha")
    asha, ravi = tmp_path / "asha", tmp_path / "ravi"
    (asha / "a.txt").write_text("a\n")
    git(asha, "add", "a.txt")
    git(asha, "commit", "-qm", "First")
    git(asha, "push", "-q", "origin", "main")
    git(tmp_path, "clone", "-q", "remote.git", "ravi")
    git(asha, "switch", "-qc", "fix/login")
    (asha / "login.txt").write_text("fixed\n")
    git(asha, "add", "login.txt")
    git(asha, "commit", "-qm", "Fix login")
    git(asha, "push", "-q", "origin", "fix/login")
    (ravi / "a.txt").write_text("changed\n")
    with pytest.raises(RuntimeError, match="uncommitted"):
        shares.checkout(ravi, "fix/login")
    git(ravi, "checkout", "--", "a.txt")
    assert shares.checkout(ravi, "fix/login") == "fix/login"
    assert git(ravi, "branch", "--show-current").strip() == "fix/login" and (ravi / "login.txt").exists()
    with pytest.raises(ValueError):
        shares.checkout(ravi, "../evil")


def test_a_handoff_from_one_laptop_to_another(tmp_path, monkeypatch):
    (tmp_path / "gitconfig").write_text("[user]\n\tname = T\n\temail = t@example.com\n[init]\n\tdefaultBranch = main\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    git(tmp_path, "init", "--bare", "-q", "remote.git")
    git(tmp_path, "clone", "-q", "remote.git", "web")
    asha, ravi = tmp_path / "web", tmp_path / "ravi" / "web"
    (asha / "snap.py").write_text("a\n")
    git(asha, "add", "snap.py")
    git(asha, "commit", "-qm", "First")
    git(asha, "push", "-q", "origin", "main")
    git(tmp_path, "clone", "-q", "remote.git", str(ravi))
    asked = []

    def asha_hub(method, path, body=None):
        asked.append((method, path, body))
        return {"task": "T-22", "owner": "ravi", "share": {"id": "s1"}, "message": {"id": 1}}
    monkeypatch.setattr(tools, "roots", lambda: {"web": asha})
    with pytest.raises(ValueError, match="default branch"):
        tools.hand_off(asha_hub, "T-22", "Ravi")
    git(asha, "switch", "-qc", "T-22-snap")
    (asha / "snap.py").write_text("b\n")
    git(asha, "commit", "-qam", "Snapshots table")
    with pytest.raises(ValueError, match="Push T-22-snap first"):
        tools.hand_off(asha_hub, "T-22", "Ravi")
    git(asha, "push", "-q", "-u", "origin", "T-22-snap")
    (asha / "snap.py").write_text("c\n")
    with pytest.raises(ValueError, match="uncommitted"):
        tools.hand_off(asha_hub, "T-22", "Ravi")
    git(asha, "commit", "-qam", "Migration 003")
    with pytest.raises(ValueError, match="Push your last commits"):
        tools.hand_off(asha_hub, "T-22", "Ravi")
    git(asha, "push", "-q")
    said = tools.handoff(SimpleNamespace(hub=asha_hub), "T-22", "Ravi", "Migration 003 is   written; key ghp_" + "Q" * 36)
    assert said.startswith("Handed T-22 to ravi: it's theirs on the board, branch T-22-snap of web waits for them")
    method, path, body = asked[-1]
    assert (method, path, body["to"], body["branch"], body["repo"]) == ("POST", "tasks/T-22/handoff", "Ravi", "T-22-snap", "web")
    assert body["note"].startswith("Migration 003 is written; key ") and "ghp_" not in body["note"]

    # Ravi's laptop: Take over checks the branch out and leaves a brief beside the code, out of git
    share = {"id": "s1", "kind": "branch", "repo": "web", "branch": "T-22-snap", "task": "T-22", "from": {"name": "Asha"},
             "note": "Migration 003 is written; its test fails on the read-only DB user"}
    task = {"title": "Snapshots migration", "progress": {"done": [{"text": "table created"}], "doing": [], "blockers": [],
                                                         "next": [{"text": "run migration 003"}]},
            "timeline": [{"ts": "2026-10-18T14:02:00.000Z", "member": "Asha", "summary": "Wrote migration 003; its test fails"},
                         {"ts": "2026-10-18T13:50:00.000Z", "member": "Asha", "line": "ran pytest", "summary": None}]}
    monkeypatch.setattr(tools, "roots", lambda: {"web": ravi})
    got = tools.take(lambda method, path, body=None: share if path == "shares/s1" else task, "s1")
    assert (got["repo"], got["branch"], got["task"], got["brief"]) == ("web", "T-22-snap", "T-22", ".superagents/handoff/T-22.md")
    assert got["prompt"] == "Read .superagents/handoff/T-22.md and pick up the task from where it stands."
    text = (ravi / got["brief"]).read_text(encoding="utf-8")
    assert text.startswith("# T-22: Snapshots migration\n") and "Asha handed this task to you. Branch T-22-snap of web" in text
    assert "its test fails on the read-only DB user" in text and "- Done: table created" in text and "- Next: run migration 003" in text
    assert "- 2026-10-18 14:02 Asha: Wrote migration 003; its test fails" in text and "ran pytest" not in text
    assert git(ravi, "branch", "--show-current").strip() == "T-22-snap" and git(ravi, "status", "--porcelain") == ""
    with pytest.raises(ValueError):  # a task id names a file here: nothing else is written
        shares.brief(ravi, {**share, "task": "../../x"}, task)


def test_what_the_sharing_tools_need_from_the_person():
    kinds = {n: tools.BY_NAME[n].kind for n in ("share_files", "share_branch", "team_files", "take_share", "handoff")}
    assert kinds == {"share_files": "ask", "share_branch": "ask", "team_files": "read", "take_share": "change", "handoff": "ask"}


def test_the_window_sends_picked_files_as_base64(monkeypatch):
    from fastapi.testclient import TestClient

    from superagents import server

    sent = []
    monkeypatch.setattr(server.shares, "send", lambda hub, files, to, note: sent.append((files, to, note)) or {"id": "s1"})
    state = server.State("https://hub.example", port=8765, key="k")
    client = TestClient(server.create(state), base_url="http://127.0.0.1:8765")
    client.headers["X-App-Key"] = "k"
    team = "11111111-2222-3333-4444-555555555555"
    r = client.post("/api/shares/send", json={"team": team, "to": "ravi", "note": "n",
                                              "files": [{"name": "a.txt", "data": base64.b64encode(b"hi").decode()}]})
    assert r.json() == {"id": "s1"} and sent == [([("a.txt", b"hi")], "ravi", "n")]
    assert client.post("/api/shares/send", json={"team": team, "files": [{"name": "a", "data": "@@not base64@@"}]}).status_code == 400

"""The shared workspace on the laptop: the pre-push hook tells the team which of its agents' commits a push shares (never
code), and a teammate's laptop works out, from its own checkout and without the network, which of those it lacks."""

import json
import os
import subprocess
import time

from teamloop import githook, login, messages, pushed, spool, workspace

CLOUD = {"mode": "cloud", "url": "https://hub.test", "token": "tl_x", "name": "ravi"}


def git(cwd, *args, agent=False):
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CURSOR_AGENT", "TEAMLOOP_AGENT")}
    if agent:
        env["CLAUDECODE"] = "1"
    return subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True,
                          text=True, env=env).stdout.strip()


def two_laptops(tmp_path):
    """A bare origin, Asha's clone (with TeamLoop's hooks) on T-19, and Ravi's clone of main."""
    git(tmp_path, "init", "-q", "--bare", "-b", "main", "origin.git")
    git(tmp_path, "clone", "-q", "origin.git", "asha")
    asha = tmp_path / "asha"
    (asha / "src").mkdir()
    (asha / "src" / "session.py").write_text("def session():\n    return 1\n")
    git(asha, "add", "-A")
    git(asha, "commit", "-q", "-m", "First")
    git(asha, "push", "-q", "origin", "main")
    git(tmp_path, "clone", "-q", "origin.git", "ravi")
    githook.install(asha)
    git(asha, "config", "teamloop.task", "T-19")
    return asha, tmp_path / "ravi"


def test_the_apps_own_repo_list_beside_it_is_left_alone_and_hooks_still_record(tmp_path, teamloop_home):
    from conftest import payloads
    from teamloop import hook

    teamloop_home.mkdir(parents=True, exist_ok=True)
    (teamloop_home / "repos.json").write_text(json.dumps(["C:/work/acme-web"]))  # Super Agents' connected repos, same folder
    r = tmp_path / "web"
    r.mkdir()
    git(r, "init", "-q")
    workspace.remember(r)
    assert json.loads((teamloop_home / "repos.json").read_text()) == ["C:/work/acme-web"] and workspace.known() == {"web": r}
    edit = next(p for p in payloads("claude_code", "fix_test_session.jsonl") if p.get("hook_event_name") == "PostToolUse")
    assert hook.handle("claude_code", json.dumps({**edit, "cwd": str(r)}).encode()) is not None and spool.pending()


def test_a_push_shares_only_the_agents_commits_and_never_code(tmp_path):
    asha, _ = two_laptops(tmp_path)
    (asha / "src" / "session.py").write_text("def app_session():\n    return 1\n\n\ndef helper():\n    return 2\n")
    git(asha, "commit", "-qam", "Rename session to app_session, key ghp_" + "Q" * 36, agent=True)
    (asha / "notes.txt").write_text("by hand\n")
    git(asha, "add", "notes.txt")
    git(asha, "commit", "-q", "-m", "My own notes")  # by hand: no link, not shared
    git(asha, "push", "-q", "origin", "main", agent=True)  # the real pre-push hook runs
    [e] = [spool.read(p) for p in spool.pending()]
    assert (e["kind"], e["tool"], e["repo"], e["branch"], e["task"]) == ("push", "git", "asha", "main", "T-19")
    [c] = e["push"]["commits"]
    assert c["task"] == "T-19" and c["files"] == [{"path": "src/session.py", "add": 5, "del": 1}]
    assert c["subject"].startswith("Rename session to app_session, key ") and "ghp_" not in json.dumps(e)
    assert "def app_session" not in json.dumps(e)  # never code
    lines = [f"refs/heads/main {git(asha, 'rev-parse', 'HEAD')} refs/heads/main {'0' * 40}", "refs/tags/v1 abc refs/tags/v1 def"]
    assert pushed.record(asha, "origin", lines) == []  # all on the remote already; a tag isn't a branch


def test_the_other_laptop_knows_what_it_lacks_and_what_it_changed_too(tmp_path, monkeypatch):
    asha, ravi = two_laptops(tmp_path)
    (asha / "src" / "session.py").write_text("def app_session():\n    return 1\n")
    git(asha, "commit", "-qam", "Rename session to app_session", agent=True)
    sha = git(asha, "rev-parse", "HEAD")
    git(asha, "push", "-q", "origin", "main", agent=True)
    workspace.remember(ravi)
    (ravi / "src" / "session.py").write_text("def session():\n    return 'mine'\n")  # Ravi's uncommitted change
    push = {"id": "e" * 32, "member": "asha", "repo": "ravi", "branch": "main", "at": time.time() - 120,
            "commits": [{"sha": sha[:12], "subject": "Rename session to app_session", "task": "T-19",
                         "files": [{"path": "src/session.py", "add": 1, "del": 1}]}]}
    [n] = workspace.notes([push])
    assert n["text"] == ("asha's agent pushed 1 commit to main in ravi (T-19), touching src/session.py, which you changed too: "
                         "pull before you go on.") and n["via"] == "board"
    got = {"repo": "ravi", "pushes": [push], "tasks": {"T-19": {"title": "Session API", "why": {"asha": "Renamed the session API; tests pass."}}}}
    text = workspace.changes_text(ravi, got)
    assert "- asha, 2 min ago, to main, T-19 (Session API): 1 commit" in text and f"{sha[:7]} Rename session to app_session: src/session.py +1 -1" in text
    assert "Why, from asha's session on T-19: Renamed the session API; tests pass." in text and "You changed src/session.py too" in text
    git(ravi, "checkout", "--", "src/session.py")
    git(ravi, "pull", "-q", "--ff-only")
    assert workspace.notes([push]) == [] and "has everything" in workspace.changes_text(ravi, got)

    def request(cfg, method, path, body=None):  # the connector's poll: a push becomes a note once
        assert path.startswith("/v1/messages?since=") and "warnings=1" in path
        return {"messages": [], "pushes": [{**push, "id": "f" * 32}]}
    monkeypatch.setattr(login, "request", request)
    git(ravi, "reset", "-q", "--hard", "HEAD~1")  # behind again
    assert messages.pull(CLOUD) == 1 and messages.pull(CLOUD) == 0
    assert "asha's agent pushed 1 commit to main in ravi" in messages.take("s-1")[0]["text"]

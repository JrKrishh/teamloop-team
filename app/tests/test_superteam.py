"""Super Team's runner: a teammate's prompt run against the owner's session, through a stand-in for each CLI that
talks the same JSON lines (and, on Windows, sits behind a .cmd shim like the real npm installs)."""

import datetime
import json
import os
import subprocess
import sys
import textwrap
from types import SimpleNamespace

import pytest

from superagents.runtime import superteam, tools

FAKE_CLAUDE = textwrap.dedent('''
    import json, os, sys, time
    here = os.path.dirname(os.path.abspath(__file__))
    prompt = sys.stdin.read()
    json.dump({"argv": sys.argv[1:], "stdin": prompt, "cwd": os.getcwd()}, open(os.path.join(here, "record.json"), "w"))
    if os.environ.get("FAKE_SLOW"):
        time.sleep(30)
    def say(d):
        print(json.dumps(d), flush=True)
    say({"type": "system", "subtype": "init", "session_id": "fork-123", "model": "claude-sonnet-5-5"})
    u1 = {"input_tokens": 10, "cache_creation_input_tokens": 2000, "cache_read_input_tokens": 50000, "output_tokens": 100}
    say({"type": "assistant", "message": {"id": "m1", "content": [{"type": "text", "text": "Looking at T-22."}], "usage": u1}})
    say({"type": "assistant", "message": {"id": "m1", "content": [{"type": "tool_use", "name": "Read"}], "usage": u1}})
    say({"type": "user", "message": {"content": [{"type": "tool_result", "content": "..."}]}})
    say({"type": "assistant", "message": {"id": "m2", "content": [{"type": "text", "text": "Two steps left."}],
         "usage": {"input_tokens": 5, "cache_creation_input_tokens": 0, "output_tokens": 50}}})
    say({"type": "result", "subtype": "success", "is_error": False, "result": "Two steps left: the migration and its test.",
         "session_id": "fork-123", "usage": {"input_tokens": 15, "cache_creation_input_tokens": 2000,
                                             "cache_read_input_tokens": 90000, "output_tokens": 150}})
''')

FAKE_CODEX = textwrap.dedent('''
    import json, os, sys
    here = os.path.dirname(os.path.abspath(__file__))
    prompt = sys.stdin.read()
    args = sys.argv[1:]
    json.dump({"argv": args, "stdin": prompt, "cwd": os.getcwd()}, open(os.path.join(here, "record.json"), "w"))
    def say(d):
        print(json.dumps(d), flush=True)
    say({"type": "thread.started", "thread_id": "th-1"})
    say({"type": "item.completed", "item": {"type": "agent_message", "text": "It streams events over SSE."}})
    say({"type": "turn.completed", "usage": {"input_tokens": 5000, "cached_input_tokens": 4000, "output_tokens": 200}})
    open(args[args.index("-o") + 1], "w").write("It streams events over SSE, with Last-Event-ID to resume.")
''')


def fake_cli(tmp_path, body, name):
    py = tmp_path / f"{name}.py"
    py.write_text(body, encoding="utf-8")
    if os.name == "nt":
        shim = tmp_path / f"{name}.cmd"
        shim.write_text(f'@"{sys.executable}" "{py}" %*\r\n', encoding="utf-8")
    else:
        shim = tmp_path / name
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{py}" "$@"\n', encoding="utf-8")
        shim.chmod(0o755)
    return str(shim)


def record(tmp_path):
    return json.loads((tmp_path / "record.json").read_text(encoding="utf-8"))


def prompt(**over):
    return {"id": "p1", "session": "sess-asha", "tool": "claude_code", "repo": "acme-web", "task": "T-22", "access": "read",
            "prompt": "What's left on T-22?", "from": {"id": "u1", "name": "Yang"}, "to": {"id": "u2", "name": "Asha"},
            "budget": None, **over}


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "acme-web"
    r.mkdir()
    return r


def test_claude_runs_a_read_only_fork_and_counts_new_tokens(tmp_path, repo):
    cli = fake_cli(tmp_path, FAKE_CLAUDE, "claude")
    out = superteam.run(prompt(), repo, cli, budget=None)
    assert out == {"status": "done", "result": "Two steps left: the migration and its test.", "tokens": 2165, "run_session": "fork-123"}
    seen = record(tmp_path)
    assert seen["argv"] == ["-p", "--resume", "sess-asha", "--fork-session", "--output-format", "stream-json", "--verbose",
                            "--restricted", "--strict-mcp-config", "--permission-mode", "dontAsk", "--disallowedTools",
                            "Edit,Write,MultiEdit,NotebookEdit"]
    assert seen["stdin"].startswith("[Super Team] Yang is asking, through Super Agents, with Asha's permission. You may read")
    assert seen["stdin"].endswith("What's left on T-22?") and os.path.samefile(seen["cwd"], repo)


def test_edit_access_accepts_edits_and_a_budget_stops_the_run(tmp_path, repo):
    cli = fake_cli(tmp_path, FAKE_CLAUDE, "claude")
    out = superteam.run(prompt(access="edit", prompt="--help & del *"), repo, cli, budget=1000)
    assert out["status"] == "stopped" and out["tokens"] == 2110
    assert "(Stopped: Yang's tokens for today ran out; 1,000 were left when it started.)" in out["result"]
    seen = record(tmp_path)
    assert seen["argv"][-2:] == ["--permission-mode", "acceptEdits"] and "--disallowedTools" not in seen["argv"]
    assert seen["stdin"].endswith("--help & del *")  # the prompt only ever travels on stdin


def test_a_follow_up_carries_the_thread_so_far(tmp_path, repo):
    cli = fake_cli(tmp_path, FAKE_CLAUDE, "claude")
    superteam.run(prompt(prompt="And after the migration?", thread=[{"prompt": "What's left on T-22?", "result": "Two steps."}]),
                  repo, cli, budget=None)
    stdin = record(tmp_path)["stdin"]
    assert "Earlier in this conversation with Yang:\n\nYang asked: What's left on T-22?\nThe answer was: Two steps." in stdin
    assert stdin.endswith("And after the migration?")


def test_a_run_that_takes_too_long_is_stopped(tmp_path, repo, monkeypatch):
    monkeypatch.setenv("FAKE_SLOW", "1")
    out = superteam.run(prompt(), repo, fake_cli(tmp_path, FAKE_CLAUDE, "claude"), budget=None, timeout=2)
    assert out["status"] == "stopped" and "Stopped after 1 minute." in out["result"]


def test_codex_continues_its_session_in_its_sandbox(tmp_path, repo):
    cli = fake_cli(tmp_path, FAKE_CODEX, "codex")
    out = superteam.run(prompt(tool="codex", session="019a-th-1", prompt="How does /v1/stream work?"), repo, cli, budget=None)
    assert out == {"status": "done", "result": "It streams events over SSE, with Last-Event-ID to resume.", "tokens": 1200,
                   "run_session": "th-1"}
    argv = record(tmp_path)["argv"]
    assert argv[:5] == ["exec", "resume", "019a-th-1", "-", "--json"] and "sandbox_mode=read-only" in argv


def test_the_runner_claims_runs_and_reports(tmp_path, repo):
    cli = fake_cli(tmp_path, FAKE_CLAUDE, "claude")
    calls = []
    queue = [prompt(), prompt(id="p2", repo="mobile"), prompt(id="p3", tool="codex"), prompt(id="p4", session="bad id; rm")]

    def call(method, path, body=None, query=None):
        calls.append((method, path, body, query))
        if path == "/v1/prompts/runnable":
            return 200, {"prompts": queue}
        if path.endswith("/claim"):
            pid = path.split("/")[3]
            return 200, {**next(p for p in queue if p["id"] == pid), "status": "running", "budget": None}
        return 200, {}

    runner = superteam.Runner(call, team=lambda: "team-1", repos=lambda: [{"name": "acme-web", "path": str(repo), "ok": True}],
                              clis={"claude_code": lambda: cli, "codex": lambda: None})
    assert runner.poll_once() == 4
    finished = {path.split("/")[3]: body for method, path, body, query in calls if path.endswith("/finish")}
    assert finished["p1"]["status"] == "done" and finished["p1"]["tokens"] == 2165
    leaky = superteam.Runner(call, team=lambda: "team-1", repos=lambda: [])
    leaky.run_one = lambda p: {"status": "done", "tokens": 1, "result": "Found it: STRIPE_SECRET_KEY=sk_live_abcdef1234567890 in .env"}
    calls.clear()
    leaky.poll_once()
    answers = [body["result"] for method, path, body, query in calls if path.endswith("/finish")]
    assert answers and all("sk_live_abcdef1234567890" not in a and "[hidden]" in a for a in answers)  # never on the record
    assert finished["p2"]["status"] == "failed" and "(mobile) isn't connected in Asha's Super Agents" in finished["p2"]["result"]
    assert finished["p3"]["result"] == "Codex isn't installed here."
    assert finished["p4"]["result"] == "That session id doesn't look right"
    assert all(q == {"team": "team-1"} for _, _, _, q in calls)
    assert superteam.Runner(call, team=lambda: None, repos=lambda: []).poll_once() == 0  # signed out or no team: nothing


# ---- the agents' Super Team, deadline and review tools -------------------------------------------------------------
def ctx_with(answers):
    calls = []

    def hub(method, path, body=None):
        calls.append((method, path, body))
        for prefix, reply in answers:
            if path.startswith(prefix):
                return reply(body) if callable(reply) else reply
        return {}
    return SimpleNamespace(hub=hub), calls


SESSIONS = {"sessions": [
    {"session": "s-mine", "mine": True, "owner": {"name": "Yang"}, "tool": "codex", "repo": "api", "task": None, "active": True,
     "last": 0, "turns": 1, "mode": "ask", "access": "read", "daily_tokens": None, "used_today": 0, "app_online": True},
    {"session": "s-asha", "mine": False, "owner": {"name": "Asha"}, "tool": "claude_code", "repo": "acme-web", "task": "T-22",
     "active": True, "last": 0, "turns": 9, "mode": "auto", "access": "edit", "daily_tokens": 50_000, "used_today": 12_000,
     "app_online": False}]}


def test_agents_see_and_prompt_teammates_sessions():
    prompt_back = {"id": "0" * 8 + "-0000-0000-0000-" + "0" * 12, "to": {"name": "Asha"}, "tool": "claude_code", "task": "T-22",
                   "repo": "acme-web", "access": "read", "status": "pending"}
    ctx, calls = ctx_with([("sessions", SESSIONS), ("prompts/", {**prompt_back, "from": {"name": "Yang"}, "status": "done",
                                                                "tokens": 2165, "result": "Two steps left."}),
                           ("prompts", lambda body: prompt_back)])
    listed = tools.team_sessions(ctx)
    assert "s-mine" not in listed and "s-asha: Asha's Claude Code session in acme-web on T-22, active now, 9 turns." in listed
    assert "runs automatically, can edit, you've used 12,000 of 50,000 tokens today. Their Super Agents is closed." in listed
    sent = tools.prompt_session(ctx, "What's left?", member="asha")
    assert ("POST", "prompts", {"session": "s-asha", "prompt": "What's left?"}) in calls
    assert sent.startswith("Sent to Asha's Claude Code session (T-22); Asha decides first (read only).")
    with pytest.raises(ValueError, match="No recent session of Sourabh"):
        tools.prompt_session(ctx, "hi", member="Sourabh")
    got = tools.session_prompt(ctx, prompt_back["id"])
    assert got == "Yang → Asha's Claude Code session: done, 2,165 tokens\nAnswer:\nTwo steps left."
    states = iter(["running", "running", "done"])  # her rules run it automatically: wait a little for the answer
    ctx2, _ = ctx_with([("prompts/", lambda body: {**prompt_back, "from": {"name": "Yang"}, "status": next(states), "tokens": 0,
                                                  "result": None})])
    monkey_sleep = []
    tools_time = __import__("time")
    real_sleep, tools_time.sleep = tools_time.sleep, monkey_sleep.append
    try:
        assert tools.session_prompt(ctx2, prompt_back["id"]).endswith("session: done") and monkey_sleep == [3, 3]
    finally:
        tools_time.sleep = real_sleep
    pending, _ = ctx_with([("prompts/", lambda body: {**prompt_back, "from": {"name": "Yang"}, "tokens": 0, "result": None})])
    assert tools.session_prompt(pending, prompt_back["id"]).endswith("session: pending")  # never waits on a person
    with pytest.raises(ValueError):
        tools.session_prompt(ctx, "../../etc")


def test_agents_leave_notes_for_teammates_agents():
    def sent(body):
        to = [{"name": n} for n in ("Asha", "Ravi")] if body["to"] == "task" else [None if body["to"] == "team" else {"name": "Asha"}]
        return {"messages": [{"to": t} for t in to], "skipped": ["Sourabh"] if body["to"] == "task" else []}
    ctx, calls = ctx_with([("messages", sent)])
    assert tools.message_teammate(ctx, "asha", "Renamed   /v1/session, key ghp_" + "Q" * 36) == \
        "Sent to Asha. Their coding agents read it at their next step."
    assert calls[-1][2]["text"].startswith("Renamed /v1/session, key ") and "ghp_" not in calls[-1][2]["text"] and calls[-1][2]["task"] is None
    assert tools.message_teammate(ctx, "team", "Freeze at 5") == "Sent to everyone. Their coding agents read it at their next step."
    said = tools.message_teammate(ctx, "task", "Rebase first", task="T-22")
    assert said.startswith("Sent to Asha, Ravi.") and "Not to Sourabh: they turned off notes" in said and calls[-1][2]["task"] == "T-22"


def test_deadlines_on_tasks():
    today = datetime.date.today()
    soon, late = (today + datetime.timedelta(days=3)).isoformat(), (today - datetime.timedelta(days=2)).isoformat()
    ctx, calls = ctx_with([("tasks/", lambda body: {"task": "T-4", "due": body["due"] or None}),
                           ("tasks", lambda body: {"task": "T-5", "title": body["title"], "owner": None, "due": body["due"]}),
                           ("board", {"room": "Loopers", "members": [], "tasks": [
                               {"task": "T-4", "status": "todo", "title": "Ship", "due": late},
                               {"task": "T-5", "status": "todo", "title": "Docs", "due": soon}]})])
    assert tools.create_task(ctx, "Docs", due=soon) == f"Created T-5: Docs, due {soon} (in 3 days)"
    assert tools.create_task(ctx, "Docs") == "Created T-5: Docs" and calls[-1][2]["due"] is None
    assert tools.set_deadline(ctx, "T-4", today.isoformat()) == f"T-4 is due {today.isoformat()} (today)"
    assert tools.set_deadline(ctx, "T-4", "") == "T-4 has no deadline now"
    with pytest.raises(ValueError):
        tools.set_deadline(ctx, "T-4", "next friday")
    board = tools.team_board(ctx)
    assert f"due {late} (2 days late)" in board and f"due {soon} (in 3 days)" in board


def test_git_diff_for_review(tmp_path, monkeypatch):
    repo = tmp_path / "web"
    repo.mkdir()
    git = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)  # noqa: E731
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    monkeypatch.setattr(tools, "roots", lambda: {"web": repo})
    assert "no commits yet" in tools.git_diff(None, "web")
    (repo / "app.py").write_text("print('hi')\n")
    git("add", "app.py")
    git("commit", "-qm", "first")
    git("checkout", "-qb", "T-9-greet")
    (repo / "app.py").write_text("print('hello')\n")
    git("commit", "-qam", "greet properly")
    (repo / "notes.md").write_text("draft\n")
    branch = tools.git_diff(None, "web", "main")
    assert "changes on this branch since main" in branch and "greet properly" in branch and "+print('hello')" in branch
    (repo / "app.py").write_text("print('hello, world')\n")
    assert "+print('hello, world')" in tools.git_diff(None, "")  # one repo: no name needed; uncommitted changes
    with pytest.raises(ValueError):
        tools.git_diff(None, "web", "main; rm -rf /")


def test_github_pr_for_review(monkeypatch):
    seen = []

    class Resp:
        def __init__(self, data):
            self.data = data

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(self.data).encode()

    def fake_urlopen(req, timeout=0):
        seen.append((req.full_url, req.headers.get("Authorization")))
        if req.full_url.endswith("/files?per_page=100"):
            return Resp([{"filename": "src/app.ts", "status": "modified", "additions": 3, "deletions": 1,
                          "patch": "@@ -1 +1 @@\n-old\n+new"}])
        return Resp({"title": "Retry failed payments", "user": {"login": "asha"}, "state": "open", "draft": False,
                     "head": {"ref": "T-24-retries"}, "base": {"ref": "main"}, "changed_files": 1, "body": "Three tries."})

    monkeypatch.setattr(tools.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(tools.mcpman, "load", lambda: [{"preset": "github", "enabled": True, "headers": {"Authorization": "Bearer t0k"}}])
    out = tools.github_pr(None, "https://github.com/acme/web/", 15)
    assert out.startswith("acme/web#15 Retry failed payments by asha (open): T-24-retries → main, 1 files")
    assert "--- src/app.ts (modified, +3 -1)\n@@ -1 +1 @@" in out
    assert seen[0] == ("https://api.github.com/repos/acme/web/pulls/15", "Bearer t0k")
    with pytest.raises(ValueError):
        tools.github_pr(None, "not a repo", 1)

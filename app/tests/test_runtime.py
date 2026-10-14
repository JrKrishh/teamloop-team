"""The agent runtime: modes and approvals, skills and instructions in the prompt, a real MCP server, file sandboxing,
and the terminal over its WebSocket."""

import json
import subprocess
import sys
import threading
import time

import pytest
from fastapi.testclient import TestClient

from superagents import server
from superagents.runtime import agents, loop, mcpman, skills
from teamloop import claude, codex

from tests.test_server import PORT, TEAM, Hub, signed_in


class NoMcp:
    errors: dict = {}

    def tools(self, ids):
        return []


def script(*steps):
    """A fake model: each call returns the next step and records what it was sent."""
    sent = []

    def llm(messages, tools, tier):
        sent.append({"messages": list(messages), "tools": [t["function"]["name"] for t in tools], "tier": tier})
        return steps[min(len(sent), len(steps)) - 1]
    return llm, sent


def call(name, args, cid="c1"):
    return {"content": None, "tool_calls": [{"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def answer(text):
    return {"content": text, "tool_calls": [], "model": "nebius:nvidia/nemotron-3-super-120b-a12b"}


def fake_hub(calls):
    def hub(method, path, body=None):
        calls.append((method, path, body))
        if path == "board":
            return {"room": "Loopers", "tasks": [{"task": "T-3", "status": "in_progress", "title": "Fix add", "members": ["Yang"]}],
                    "members": [{"name": "Yang", "active": True}, {"name": "Asha"}]}
        if path == "tasks":
            return {"task": "T-4", "title": body["title"], "owner": body.get("owner"), "state": "open"}
        return {}
    return hub


def run_turn(mode, llm, hub_calls, agent=None, message="plan it", approve=None):
    t = loop.Turn(chat=loop.new_chat("agent-s"), agent=agent or agents.get("agent-s"), message=message, attachments=[],
                  mode=mode, model="auto", hub=fake_hub(hub_calls), llm=llm, mcp=NoMcp(), person="Yang")
    th = threading.Thread(target=t.run, daemon=True)
    th.start()
    deadline = time.time() + 10
    while not t.done and time.time() < deadline:
        for e in t.events:
            if e["kind"] == "tool" and e["status"] == "asking" and e["id"] not in t.answers:
                t.decide(e["id"], approve(e) if approve else True)
        time.sleep(0.02)
    th.join(5)
    return t


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("TEAMLOOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "userhome"))
    monkeypatch.setenv("HOME", str(tmp_path / "userhome"))
    return tmp_path


def statuses(t, name):
    return [e["status"] for e in t.events if e["kind"] == "tool" and e["name"] == name]


def test_manual_asks_before_a_change_and_reads_run_free(home):
    hub_calls = []
    llm, sent = script(call("team_board", {}, "r1"), call("create_task", {"title": "Rate limits", "owner": "Asha"}, "w1"), answer("Added T-4."))
    t = run_turn("manual", llm, hub_calls)
    assert statuses(t, "team_board") == ["running", "done"]
    assert statuses(t, "create_task") == ["asking", "running", "done"]
    assert ("POST", "tasks", {"title": "Rate limits", "owner": "Asha", "task": "", "due": None}) in hub_calls
    assert [e["kind"] for e in t.events][-2:] == ["answer", "end"] and t.events[-2]["text"] == "Added T-4."
    tool_msgs = [m for m in sent[2]["messages"] if m["role"] == "tool"]
    assert tool_msgs[-1]["content"] == "Created T-4: Rate limits (owner Asha)"
    saved = loop.load_chat(t.chat["id"])
    assert saved["title"] == "plan it" and saved["view"][0]["answer"] == "Added T-4."


def test_the_answer_carries_the_turns_usage_and_agents_can_read_the_teams(home):
    hub_calls = []
    step = call("team_usage", {"days": 7})
    llm, sent = script({**step, "usage": {"in": 900, "out": 40}}, {**answer("T-3 cost the most."), "usage": {"in": 1500, "out": 60}})
    summary = {"days": 7, "scope": "team", "coding": {"tokens": 2_400_000, "turns": 31, "sessions": 4, "cr": 90_000_000},
               "tools": {"claude_code": {"tokens": 2_000_000}, "codex": {"tokens": 400_000}},
               "agents": {"tokens": 52_000, "calls": 40},
               "tasks": [{"task": "T-3", "tokens": 1_900_000, "people": ["Yang"]}],
               "people": [{"name": "Asha", "total": 400_000}, {"name": "Yang", "total": 2_052_000}],
               "by_day": [{"day": "2026-10-13", "claude_code": 900_000, "codex": 0, "agents": 2000}]}

    def hub(method, path, body=None):
        return summary if path.startswith("usage") else fake_hub(hub_calls)(method, path, body)

    t = loop.Turn(chat=loop.new_chat("agent-s"), agent=agents.get("agent-s"), message="Which task cost the most?",
                  attachments=[], mode="manual", model="auto", hub=hub, llm=llm, mcp=NoMcp(), person="Yang")
    t.run()
    result = [m["content"] for m in sent[1]["messages"] if m["role"] == "tool"][0]
    assert "Coding agents: 2.4M tokens over 31 turns in 4 sessions (Claude Code 2.0M, Codex 400k; cache reads 90.0M)" in result
    assert "T-3 1.9M (Yang)" in result and "By person: Asha 400k; Yang 2.1M" in result and "10-13 902k" in result
    assert t.events[-2]["usage"] == {"calls": 2, "in": 2400, "out": 100}
    assert loop.load_chat(t.chat["id"])["view"][0]["usage"]["calls"] == 2


def test_declining_stops_the_change(home):
    hub_calls = []
    llm, sent = script(call("close_task", {"task": "T-3"}), answer("Left it open."))
    t = run_turn("manual", llm, hub_calls, approve=lambda e: False)
    assert statuses(t, "close_task") == ["asking", "declined"] and not any(c[0] == "PATCH" for c in hub_calls)
    assert "declined" in [m for m in sent[1]["messages"] if m["role"] == "tool"][0]["content"]


def start_waiting(mode, llm, hub_calls):
    """A turn started in `mode`, running until its first call waits for a yes."""
    t = loop.Turn(chat=loop.new_chat("agent-s"), agent=agents.get("agent-s"), message="plan it", attachments=[], mode=mode,
                  model="auto", hub=fake_hub(hub_calls), llm=llm, mcp=NoMcp(), person="Yang")
    th = threading.Thread(target=t.run, daemon=True)
    th.start()
    deadline = time.time() + 10
    while not any(e["kind"] == "tool" and e["status"] == "asking" for e in t.events) and time.time() < deadline:
        time.sleep(0.02)
    return t, th


def test_switching_to_auto_while_it_runs(home):
    hub_calls = []
    llm, sent = script(call("create_task", {"title": "Rate limits"}, "w1"), call("create_task", {"title": "Retries"}, "w2"), answer("Added both."))
    t, th = start_waiting("manual", llm, hub_calls)
    t.set_mode("auto")  # the person switches while the first change waits for a yes
    th.join(10)
    assert statuses(t, "create_task") == ["asking", "running", "done", "running", "done"]  # that one ran; the next didn't ask
    assert sum(c[1] == "tasks" for c in hub_calls) == 2 and t.mode == "auto"
    assert {"kind": "mode", "mode": "auto"}.items() <= next(e for e in t.events if e["kind"] == "mode").items()
    assert sent[1]["messages"][-1] == {"role": "user", "content": f"(The person switched this chat to auto mode. {loop.MODE_RULES['auto']})"}


def test_switching_to_plan_queues_what_waits(home):
    hub_calls = []
    llm, sent = script(call("create_task", {"title": "Rate limits"}, "w1"), answer("1. Add the rate limits task"))
    t, th = start_waiting("manual", llm, hub_calls)
    t.set_mode("plan")
    th.join(10)
    assert statuses(t, "create_task") == ["asking", "planned"] and not any(c[1] == "tasks" for c in hub_calls)
    assert len(t.planned) == 1 and "switched to plan mode" in [m for m in sent[1]["messages"] if m["role"] == "tool"][0]["content"]


def test_plan_queues_changes_until_run_plan(home):
    hub_calls = []
    llm, sent = script(call("create_task", {"title": "Rate limits"}), answer("1. Add rate limits task"))
    t = run_turn("plan", llm, hub_calls)
    assert statuses(t, "create_task") == ["planned"] and not any(c[1] == "tasks" for c in hub_calls)
    assert "Not run: plan mode" in [m for m in sent[1]["messages"] if m["role"] == "tool"][0]["content"]
    assert t.events[-1] == {"i": len(t.events) - 1, "kind": "end", "planned": 1}
    t.run_plan()
    assert statuses(t, "create_task")[-2:] == ["running", "done"] and any(c[1] == "tasks" for c in hub_calls)


def test_a_plan_in_prose_is_asked_once_for_its_calls(home):
    hub_calls = []
    llm, sent = script(answer("1. Close T-3\n2. Add a rate limits task"), call("close_task", {"task": "T-3"}), answer("Queued."))
    t = run_turn("plan", llm, hub_calls)
    assert sent[1]["messages"][-1] == {"role": "user", "content": loop.PLAN_NUDGE}
    assert statuses(t, "close_task") == ["planned"] and t.events[-2]["text"] == "1. Close T-3\n2. Add a rate limits task"
    assert not any(c[0] == "PATCH" for c in hub_calls)
    llm, sent = script(answer("Nothing to change: T-3 is already closed."), answer("No changes."))
    t = run_turn("plan", llm, [])
    assert len(sent) == 2 and t.events[-2]["text"] == "Nothing to change: T-3 is already closed." and t.events[-1]["planned"] == 0
    llm, sent = script(call("close_task", {"task": "T-3"}, "p1"), answer("1. Close T-3\n2. Add a task"),
                       call("create_task", {"title": "Rate limits"}, "p2"), answer("All queued."))
    t = run_turn("plan", llm, [])  # one step queued, one only in the prose: asked to queue the rest
    assert sent[2]["messages"][-1]["content"].startswith('Queued so far: close_task {"task": "T-3"}.')
    assert t.events[-1]["planned"] == 2 and t.events[-2]["text"] == "1. Close T-3\n2. Add a task"
    llm, sent = script(answer("Done already."))
    run_turn("manual", llm, [])
    assert len(sent) == 1  # only plan mode asks again


def test_a_long_turn_keeps_working_with_a_small_context(home):
    """Like Claude Code: no stop after a couple of dozen steps; old tool output is cut and the oldest steps fold, so every
    step stays inside the hub's limits (200 messages, 400k characters)."""
    boards = []

    def hub(method, path, body=None):
        boards.append(1)
        return {"room": f"Loopers {len(boards)}", "members": [],
                "tasks": [{"task": f"T-{i}", "status": "todo", "title": "x" * 120} for i in range(80)]}  # ~10k characters

    sent = []

    def llm(messages, tools, tier):
        sent.append(json.loads(json.dumps(messages)))  # as sent: compact() changes older messages in place afterwards
        n = len(sent)
        return call("team_board", {}, f"c{n}") if n <= 150 else answer("Finished.")

    t = loop.Turn(chat=loop.new_chat("agent-s"), agent=agents.get("agent-s"), message="check the board a lot", attachments=[],
                  mode="auto", model="auto", hub=hub, llm=llm, mcp=NoMcp(), person="Yang")
    t.run()
    assert t.events[-2]["text"] == "Finished." and len(sent) == 151
    assert max(len(m) for m in sent) <= 200 and max(len(json.dumps(m)) for m in sent) < 250_000
    last = sent[-1]
    results = [m["content"] for m in last if m["role"] == "tool"]
    assert all(len(r) > 9000 for r in results[-loop.KEEP_WHOLE:]) and all(r.endswith(loop.CUT) for r in results[:-loop.KEEP_WHOLE])
    head = 2  # the system prompt and the person's message (a new chat has no history)
    assert last[head]["role"] == "user" and last[head]["content"].startswith(loop.FOLDED.strip())
    assert "- team_board {} → Team Loopers 2." in last[head]["content"]  # the first step (1 was the prompt's), folded to a line
    ids = {c["id"] for m in last if m.get("tool_calls") for c in m["tool_calls"]}
    assert all(m["tool_call_id"] in ids for m in last if m["role"] == "tool")  # every result still follows its call


def test_at_the_step_limit_it_says_where_it_got_to(home, monkeypatch):
    monkeypatch.setattr(loop, "MAX_STEPS", 4)
    llm, sent = script(*[call("team_board", {}, f"c{i}") for i in range(4)], answer("Read the board 4 times; T-3 still needs review."))
    t = run_turn("auto", llm, [])
    assert len(sent) == 5 and sent[-1]["messages"][-1] == {"role": "user", "content": loop.WRAP_UP.format(n=4)}
    assert t.events[-2]["text"] == "Read the board 4 times; T-3 still needs review."
    llm, sent = script(*[call("team_board", {}, f"d{i}") for i in range(5)])  # it still only calls tools: said for it
    t = run_turn("auto", llm, [])
    assert t.events[-2]["text"] == "I took 4 steps on this and stopped there. Ask me to continue."


def test_the_same_call_with_the_same_result_is_named_a_loop(home):
    llm, sent = script(*[call("team_board", {}, f"r{i}") for i in range(3)], answer("ok"))
    run_turn("auto", llm, [])
    results = [m["content"] for m in sent[-1]["messages"] if m["role"] == "tool"]
    assert not results[1].endswith(loop.REPEAT_NUDGE.format(n=2)) and results[2].endswith(loop.REPEAT_NUDGE.format(n=3))


def test_auto_runs_changes_but_shell_commands_still_ask(home):
    hub_calls = []
    llm, _ = script(call("create_task", {"title": "x"}, "a1"), call("run_command", {"command": "echo hi"}, "a2"), answer("ok"))
    asked = []
    t = run_turn("auto", llm, hub_calls, approve=lambda e: asked.append(e["name"]) or False)
    assert statuses(t, "create_task") == ["running", "done"]
    assert statuses(t, "run_command") == ["asking", "declined"] and asked == ["run_command"]


def test_bad_calls_are_reported_to_the_model(home):
    llm, sent = script({"content": None, "tool_calls": [{"id": "b1", "type": "function", "function": {"name": "nope", "arguments": "{}"}},
                                                        {"id": "b2", "type": "function", "function": {"name": "team_board", "arguments": "{oops"}}]},
                       answer("sorry"))
    t = run_turn("auto", llm, [])
    results = [m["content"] for m in sent[1]["messages"] if m["role"] == "tool"]
    assert results[0].startswith("Error: there is no tool called nope") and "not valid JSON" in results[1]
    assert statuses(t, "nope") == ["failed"]


def test_the_prompt_carries_skills_instructions_and_tool_groups(home):
    me = agents.save(None, {"name": "Reviewer", "instructions": "Review like a staff engineer.", "tools": {"team": True, "files": False,
                                                                                                          "terminal": False, "browser": False}})
    skills.save("release-notes", "Write release notes from merged work", "Group by feature.")
    me = agents.save(me["id"], {"skills": ["karpathy-guidelines", "release-notes"]})
    llm, sent = script(answer("hi"))
    run_turn("manual", llm, [], agent=me)
    system = sent[0]["messages"][0]["content"]
    assert system.startswith("You are Reviewer") and "Members: Yang, Asha" not in system and "members: Yang, Asha" in system
    assert "## Skill: karpathy-guidelines (always on)" in system and "Surgical Changes" in system
    assert "- release-notes: Write release notes from merged work" in system
    assert system.rstrip().endswith("Review like a staff engineer.")
    assert "run_command" not in sent[0]["tools"] and "read_file" not in sent[0]["tools"]
    assert {"team_board", "create_task", "load_skill"} <= set(sent[0]["tools"])


def test_agents_store(home):
    assert [a["id"] for a in agents.all_agents()] == ["agent-s"]
    assert agents.get("agent-s")["skills"] == ["karpathy-guidelines", "code-review"]
    a = agents.save(None, {"name": "  Release   manager ", "color": "#3E9B6B", "model": "ultra", "mode": "plan", "bogus": 1})
    assert a["name"] == "Release manager" and a["model"] == "ultra" and "bogus" not in a
    agents.save("agent-s", {"instructions": "Be brief."})
    assert agents.get("agent-s")["instructions"] == "Be brief." and agents.get("agent-s")["builtin"]
    with pytest.raises(PermissionError):
        agents.delete("agent-s")
    agents.delete(a["id"])
    assert len(agents.all_agents()) == 1


def test_skills_import_from_claude_code(home):
    src = home / "userhome" / ".claude" / "skills" / "git-human-commits"
    src.mkdir(parents=True)
    (src / "SKILL.md").write_text("---\nname: git-human-commits\ndescription: Commit like a person\n---\nWrite short subjects.\n")
    assert [s.name for s in skills.claude_code_skills()] == ["git-human-commits"]
    s = skills.import_claude_code("git-human-commits")
    assert s.body().strip() == "Write short subjects." and not s.bundled
    assert set(skills.all_skills()) >= {"karpathy-guidelines", "git-human-commits"}
    assert skills.all_skills()["karpathy-guidelines"].files() == ["EXAMPLES.md", "SOURCE.md"]
    with pytest.raises(ValueError):
        skills.save("Bad Name", "x", "y")
    mine = skills.save("karpathy-guidelines", "Mine", "Think first.")  # customizing a built-in keeps its other files
    assert not mine.bundled and mine.files() == ["EXAMPLES.md", "SOURCE.md"] and mine.body().strip() == "Think first."
    skills.delete("karpathy-guidelines")
    assert skills.all_skills()["karpathy-guidelines"].bundled


def test_a_real_mcp_server(home):
    """Our own connector's MCP server (python -m teamloop mcp) as the server under test."""
    c = mcpman.custom({"name": "TeamLoop", "command": sys.executable, "args": ["-m", "teamloop", "mcp"]})
    mcpman.save_all([c])
    m = mcpman.Manager()
    tools = {t.name: t for t in m.tools([c["id"]], timeout=60)}
    assert {"task_start", "report_progress", "mark_blocked", "get_team_status"} <= set(tools), m.errors
    assert tools["get_team_status"].full.startswith("mcp__teamloop-") and len(tools["get_team_status"].full) <= 64
    text, is_error = m.call(tools["get_team_status"], {})
    assert isinstance(text, str) and text
    task = m.live[c["id"]][1]
    m.drop(c["id"])
    assert c["id"] not in m.live and task.done()  # closed by the task that opened it, so the server process is gone
    assert {"task_start", "get_team_status"} <= set(m.test(c))
    broken = mcpman.custom({"name": "Broken", "command": sys.executable, "args": ["-c", "raise SystemExit(3)"]})
    mcpman.save_all([c, broken])
    assert m.tools([broken["id"]], timeout=30) == [] and broken["id"] in m.errors


def test_effort_reaches_the_model_with_room_to_think(client, monkeypatch):
    sent, hub, old = [], server.cloud, {"hub": False}

    def cloud(state, method, path, body=None, query=None, token=None):
        if path == "/v1/llm":
            sent.append(body)
            if old["hub"] and body["max_tokens"] > 4000:
                return 422, {"detail": "max_tokens"}
            return 200, {"content": "Done.", "tool_calls": [], "model": "nebius:nvidia/nemotron-3-super-120b-a12b"}
        return hub(state, method, path, body, query, token)

    monkeypatch.setattr(server, "cloud", cloud)
    def run(effort):
        tid = client.post("/api/turns", json={"message": "hi", "team": TEAM, **({"effort": effort} if effort else {})}).json()["turn"]
        deadline = time.time() + 10
        while not client.get(f"/api/turns/{tid}").json()["done"] and time.time() < deadline:
            time.sleep(0.05)
        return client.get(f"/api/turns/{tid}").json()["events"]

    run(None)
    run("high")
    assert [(b["effort"], b["max_tokens"]) for b in sent] == [("medium", 4000), ("high", 6000)]  # Medium unless asked
    old["hub"] = True  # a hub from before effort: at most 4000 tokens a step
    assert any(e["kind"] == "answer" for e in run("max")) and [b["max_tokens"] for b in sent[2:]] == [8000, 4000]
    assert client.post("/api/turns", json={"message": "hi", "team": TEAM, "effort": "turbo"}).status_code == 422
    assert client.post("/api/prefs", json={"effort": "max"}).json()["effort"] == "max"  # remembered like the model


def test_citation_marks_are_taken_out_of_answers():
    for mark in ('【{"cursor": 0, "loc": 0}】', "【3†source】", "【38aaba8cab3c470287a8571e7d5b25f7】"):
        assert loop.CITE_MARK.sub("", f"T-11 is blocked {mark}. All else is moving.") == "T-11 is blocked. All else is moving."


def test_chats_are_listed_with_the_repo_they_worked_in(home, monkeypatch):
    work = home / "work"
    monkeypatch.setattr(loop.store, "repos", lambda: [str(work / "acme-web"), str(work / "api")])

    def view(*calls):
        return [{"events": [{"kind": "tool", "name": name, "args": args} for name, args in calls]}]

    loop.save_chat({"id": "c-web", "title": "Fix the header", "updated": 3, "view": view(
        ("read_file", {"path": "acme-web/src/app.ts"}), ("run_command", {"command": "npm test", "cwd": "acme-web"}),
        ("read_file", {"path": "api/README.md"}))})  # mostly acme-web
    loop.save_chat({"id": "c-api", "title": "Check the API", "updated": 2,
                    "view": view(("read_file", {"path": str(work / "api" / "main.py")}))})  # an absolute path inside a repo
    loop.save_chat({"id": "c-team", "title": "What's blocked?", "updated": 1, "view": view(("team_board", {}))})
    assert {c["id"]: c["project"] for c in loop.list_chats()} == {"c-web": "acme-web", "c-api": "api", "c-team": None}


@pytest.fixture
def client(home, monkeypatch):
    monkeypatch.setattr(claude, "register_mcp", lambda cwd, scope: "registered (test)")
    monkeypatch.setattr(codex, "cli", lambda: None)
    monkeypatch.setattr(server, "cloud", Hub())
    state = server.State("https://hub.example", port=PORT, key="the-key")
    c = TestClient(server.create(state, open_url=lambda u: None), base_url=f"http://127.0.0.1:{PORT}")
    c.headers["X-App-Key"] = "the-key"
    signed_in(monkeypatch, c)
    return c


def test_files_stay_inside_connected_repos(client, home):
    root = home / "proj"
    (root / "src").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    (root / "src" / "app.py").write_text("print('hi')\n")
    (root / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\nxx")
    secret = home / "secret.txt"
    secret.write_text("no")
    client.post("/api/laptop/repos", json={"path": str(root)})
    assert client.get("/api/files/roots").json()["roots"][0]["name"] == "proj"
    names = [e["name"] for e in client.get("/api/files/list", params={"path": "proj"}).json()["entries"]]
    assert {"src", "logo.png"} <= set(names) and ".git" not in names and names.index("src") < names.index("logo.png")
    r = client.get("/api/files/read", params={"path": "proj/src/app.py"}).json()
    assert r["kind"] == "text" and r["text"] == "print('hi')\n"
    assert client.get("/api/files/read", params={"path": "proj/logo.png"}).json()["kind"] == "image"
    assert client.get("/api/files/raw", params={"path": "proj/logo.png"}).content.startswith(b"\x89PNG")
    assert client.get("/api/files/read", params={"path": "proj/../secret.txt"}).status_code == 403
    assert client.get("/api/files/read", params={"path": str(secret)}).status_code == 403


def test_terminal_over_websocket(client, home):
    origin = {"host": f"127.0.0.1:{PORT}", "origin": f"http://127.0.0.1:{PORT}"}  # the test client defaults to "testserver"
    with pytest.raises(Exception):
        with client.websocket_connect("/api/terminal?k=wrong", headers=origin) as ws:
            ws.receive_text()
    with client.websocket_connect("/api/terminal?k=the-key&cols=80&rows=20", headers=origin) as ws:
        ws.send_text(json.dumps({"t": "in", "d": "echo super-agents-ok\r"}))
        seen = ""
        deadline = time.time() + 20
        while "super-agents-ok" not in seen.replace("echo super-agents-ok", "") and time.time() < deadline:
            seen += ws.receive_text()
        assert "super-agents-ok" in seen.replace("echo super-agents-ok", "")

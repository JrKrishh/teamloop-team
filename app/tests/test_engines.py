"""Turns on the person's own Claude Code or Codex, through stand-ins for each CLI that talk the same JSON lines
(Claude Code's streaming mode, as its SDK drives it; Codex's exec --json) and sit behind a .cmd shim on Windows."""

import json
import os
import sys
import textwrap
import threading
import time

import pytest

from superagents.runtime import agents, engines, loop

FAKE_CLAUDE = textwrap.dedent('''
    import json, os, sys
    here = os.path.dirname(os.path.abspath(__file__))
    argv, seen = sys.argv[1:], []
    def rec():
        log = os.path.join(here, "claude-runs.json")
        runs = json.load(open(log)) if os.path.exists(log) else []
        if runs and runs[-1]["pid"] == os.getpid():
            runs[-1]["seen"] = seen
        else:
            runs.append({"pid": os.getpid(), "argv": argv, "seen": seen, "cwd": os.getcwd()})
        json.dump(runs, open(log, "w"))
    def say(d):
        print(json.dumps(d), flush=True)
    def nxt():
        line = sys.stdin.readline()
        if not line:
            rec()
            sys.exit(0)
        d = json.loads(line)
        seen.append(d)
        rec()
        return d
    def asked(rid, name, inp, tuid):
        say({"type": "control_request", "request_id": rid,
             "request": {"subtype": "can_use_tool", "tool_name": name, "input": inp, "tool_use_id": tuid}})
        while True:
            d = nxt()
            if d.get("type") == "control_response" and d["response"]["request_id"] == rid:
                return d["response"]["response"]
    def tool(tuid, name, inp):
        say({"type": "assistant", "message": {"id": "m-" + tuid, "content": [{"type": "tool_use", "id": tuid, "name": name, "input": inp}]}})
    def done(tuid, text, failed=False):
        say({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tuid, "content": text, "is_error": failed}]}})
    def result(text, sid):
        say({"type": "result", "subtype": "success", "is_error": False, "result": text, "session_id": sid, "num_turns": 2,
             "usage": {"input_tokens": 10, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 5000, "output_tokens": 20}})
    init = nxt()
    say({"type": "control_response", "response": {"subtype": "success", "request_id": init["request_id"], "response": {}}})
    first = nxt()
    sid = argv[argv.index("--resume") + 1] if "--resume" in argv else "cc-1"
    if "--resume" in argv and os.environ.get("FAKE_GONE"):
        print("No conversation found with session ID: " + sid, file=sys.stderr)
        sys.exit(1)
    say({"type": "system", "subtype": "init", "session_id": sid, "model": "claude-opus-5-5"})
    play, path = os.environ.get("FAKE_PLAY", "edit"), os.environ.get("FAKE_FILE", "notes.md")
    if play == "edit":
        say({"type": "assistant", "message": {"id": "m1", "content": [{"type": "text", "text": "I'll fix the typo."}]}})
        tool("tu1", "Read", {"file_path": path})
        done("tu1", "teh end")
        edit = {"file_path": path, "old_string": "teh", "new_string": "the"}
        tool("tu2", "Edit", edit)
        r = asked("p1", "Edit", edit, "tu2")
        done("tu2", "Edited" if r["behavior"] == "allow" else r["message"], r["behavior"] != "allow")
        result("Fixed the typo." if r["behavior"] == "allow" else "Left it as it was.", sid)
    elif play == "bash":
        tool("tu3", "Bash", {"command": "npm test"})
        r = asked("p2", "Bash", {"command": "npm test"}, "tu3")
        done("tu3", "12 passed" if r["behavior"] == "allow" else r["message"], r["behavior"] != "allow")
        result("Tests pass." if r["behavior"] == "allow" else "Didn't run them.", sid)
    elif play == "plan":
        plan = {"plan": "1. Fix the typo in notes.md\\n2. Add a test for it"}
        tool("tu4", "ExitPlanMode", plan)
        r = asked("p3", "ExitPlanMode", plan, "tu4")
        done("tu4", r.get("message", ""), True)
        result("I'll wait for the go-ahead.", sid)
    elif play == "steer":
        say({"type": "assistant", "message": {"id": "m5", "content": [{"type": "text", "text": "Looking."}]}})
        nxt()  # the note typed while it works
        result("First answer.", sid)
        result("Used pytest, as you asked.", sid)
    while sys.stdin.readline():  # the app closes stdin once each message has its answer
        pass
    rec()
''')

FAKE_CODEX = textwrap.dedent('''
    import json, os, sys
    here = os.path.dirname(os.path.abspath(__file__))
    args, prompt = sys.argv[1:], sys.stdin.read()
    log = os.path.join(here, "codex-runs.json")
    runs = json.load(open(log)) if os.path.exists(log) else []
    runs.append({"argv": args, "stdin": prompt, "cwd": os.getcwd()})
    json.dump(runs, open(log, "w"))
    def say(d):
        print(json.dumps(d), flush=True)
    say({"type": "thread.started", "thread_id": "th-1"})
    say({"type": "item.completed", "item": {"id": "r1", "type": "reasoning", "text": "..."}})
    cmd = {"id": "c1", "type": "command_execution", "command": "pytest -q", "aggregated_output": "", "status": "in_progress"}
    say({"type": "item.started", "item": cmd})
    say({"type": "item.completed", "item": {**cmd, "aggregated_output": "3 passed", "exit_code": 0, "status": "completed"}})
    say({"type": "item.completed", "item": {"id": "f1", "type": "file_change", "status": "completed",
                                            "changes": [{"path": os.environ.get("FAKE_FILE", "x"), "kind": "update"}]}})
    say({"type": "item.completed", "item": {"id": "a1", "type": "agent_message", "text": "Done: fixed it."}})
    say({"type": "turn.completed", "usage": {"input_tokens": 5000, "cached_input_tokens": 4000, "output_tokens": 200}})
    open(args[args.index("-o") + 1], "w").write("Fixed the typo; 3 tests pass.")
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


def runs(tmp_path, tool):
    return json.loads((tmp_path / f"{tool}-runs.json").read_text(encoding="utf-8"))


@pytest.fixture
def lab(tmp_path, monkeypatch):
    """A laptop with acme-web connected, Claude Code last used on Opus 5.5 (1M), and both CLIs (stand-ins)."""
    home = tmp_path / "home"
    repo = tmp_path / "acme-web"
    repo.mkdir()
    (repo / "notes.md").write_text("teh end\n", encoding="utf-8")
    monkeypatch.setenv("TEAMLOOP_HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "userhome"))
    monkeypatch.setenv("HOME", str(tmp_path / "userhome"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("FAKE_FILE", str(repo / "notes.md"))
    home.mkdir()
    (home / "repos.json").write_text(json.dumps([str(repo)]), encoding="utf-8")
    t = tmp_path / "claude/projects/E--acme-web/s-1.jsonl"
    t.parent.mkdir(parents=True)
    t.write_text(json.dumps({"type": "assistant", "requestedModel": "claude-opus-5-5[1m]", "message": {"model": "claude-opus-5-5"}}) + "\n",
                 encoding="utf-8")
    (tmp_path / "codex").mkdir()
    (tmp_path / "codex/config.toml").write_text('model = "gpt-6-astra"\n', encoding="utf-8")
    clis = {"claude_code": fake_cli(tmp_path, FAKE_CLAUDE, "claude"), "codex": fake_cli(tmp_path, FAKE_CODEX, "codex")}
    monkeypatch.setattr(engines, "CLIS", {k: (lambda v=v: v) for k, v in clis.items()})
    return tmp_path, repo


def hub(method, path, body=None):
    if path == "board":
        return {"room": "Loopers", "members": [{"name": "Yang"}, {"name": "Asha"}], "tasks": [],
                "rules": {"decisions": [{"text": "Postgres, not Mongo", "by": {"name": "Asha"}}]}}
    return {}


def start(model, mode="manual", chat=None, message="Fix the typo in notes.md", effort="medium"):
    t = engines.CliTurn(chat=chat or loop.new_chat("agent-s"), agent=agents.get("agent-s"), message=message, attachments=[],
                        mode=mode, model=model, hub=hub, llm=None, mcp=None, person="Yang", effort=effort)
    threading.Thread(target=t.run, daemon=True).start()
    return t


def drive(t, approve=lambda e: True, until=lambda t: t.done, timeout=20):
    deadline = time.time() + timeout
    while not until(t) and time.time() < deadline:
        for e in list(t.events):
            if e["kind"] == "tool" and e["status"] == "asking" and e["id"] not in t.answers:
                t.decide(e["id"], approve(e))
        time.sleep(0.02)
    assert until(t), [e["kind"] for e in t.events]
    return t


def statuses(t, name):
    return [e["status"] for e in t.events if e["kind"] == "tool" and e["name"] == name]


def said(t, kind):
    return [e for e in t.events if e["kind"] == kind]


def test_claude_code_asks_before_an_edit_in_manual_and_continues_its_session(lab):
    tmp, repo = lab
    t = drive(start("claude_code"))
    assert said(t, "answer")[0]["text"] == "Fixed the typo." and said(t, "answer")[0]["model"] == "Claude Code · Opus 5.5 (1M)"
    assert said(t, "start")[0]["model"] == "Claude Code · Opus 5.5 (1M)" and not said(t, "error")
    assert statuses(t, "read_file") == ["running", "done"]
    assert statuses(t, "edit_file") == ["running", "asking", "running", "done"]
    card = next(e for e in t.events if e.get("name") == "edit_file")
    assert card["args"] == {"path": "acme-web/notes.md", "old": "teh", "new": "the"} and card["access"] == "change"
    assert [e["text"] for e in said(t, "text")] == ["I'll fix the typo."]
    assert t.spent == {"calls": 2, "in": 110, "out": 20}
    run = runs(tmp, "claude")[0]
    assert run["argv"][:10] == ["-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                                "--permission-prompt-tool", "stdio", "--permission-mode", "default"]
    assert run["argv"][10:] == ["--effort", "medium", "--model", "claude-opus-5-5[1m]"] and os.path.samefile(run["cwd"], repo)
    first = run["seen"][1]["message"]["content"]
    assert first.startswith("[Super Agents] You're Agent S, an agent in Super Agents") and "Postgres, not Mongo (decided by Asha)" in first
    assert "[Manual mode: Yang approves each change before it runs, and every command.]\n\nFix the typo in notes.md" in first
    allowed = next(d for d in run["seen"] if d["type"] == "control_response")["response"]["response"]
    assert allowed == {"behavior": "allow", "updatedInput": {"file_path": str(repo / "notes.md"), "old_string": "teh", "new_string": "the"}}
    assert t.chat["cli"] == {"tool": "claude_code", "session": "cc-1", "cwd": str(repo)}
    assert loop.load_chat(t.chat["id"])["cli"]["session"] == "cc-1"  # kept with the chat

    again = drive(start("claude_code", chat=loop.load_chat(t.chat["id"]), message="Thanks"))  # a follow-up continues it
    second = runs(tmp, "claude")[1]
    assert second["argv"][second["argv"].index("--resume") + 1] == "cc-1"
    assert second["seen"][1]["message"]["content"] == "[Manual mode: Yang approves each change before it runs, and every command.]\n\nThanks"
    assert said(again, "answer")[0]["text"] == "Fixed the typo."


def test_auto_runs_changes_but_a_command_still_asks(lab, monkeypatch):
    tmp, _ = lab
    t = drive(start("claude_code", mode="auto"))
    assert statuses(t, "edit_file") == ["running", "running", "done"]  # no asking
    monkeypatch.setenv("FAKE_PLAY", "bash")
    t = drive(start("claude_code", mode="auto"), approve=lambda e: False)
    assert statuses(t, "run_command") == ["running", "asking", "declined"]
    assert said(t, "answer")[0]["text"] == "Didn't run them."
    denied = next(d for d in runs(tmp, "claude")[1]["seen"] if d["type"] == "control_response")["response"]["response"]
    assert denied["behavior"] == "deny" and "declined" in denied["message"]


def test_plan_mode_keeps_claude_codes_plan_and_run_plan_carries_it_out(lab, monkeypatch):
    tmp, repo = lab
    monkeypatch.setenv("FAKE_PLAY", "plan")
    t = drive(start("claude_code", mode="plan"))
    assert said(t, "answer")[0]["text"] == "1. Fix the typo in notes.md\n2. Add a test for it" and len(t.planned) == 2
    assert said(t, "end")[0]["planned"] == 2 and not statuses(t, "exit_plan")
    first = runs(tmp, "claude")[0]
    assert first["argv"][first["argv"].index("--permission-mode") + 1] == "plan"
    kept = next(d for d in first["seen"] if d["type"] == "control_response")["response"]["response"]
    assert kept == {"behavior": "deny", "message": engines.PLAN_KEPT}
    monkeypatch.setenv("FAKE_PLAY", "edit")
    t.run_plan()  # Run plan: the same session carries the plan out, its changes running without asking
    carry = runs(tmp, "claude")[1]
    assert carry["argv"][carry["argv"].index("--resume") + 1] == "cc-1"
    assert carry["argv"][carry["argv"].index("--permission-mode") + 1] == "default"
    assert carry["seen"][1]["message"]["content"].startswith("[Auto mode: ") and "Yang ran your plan: carry it out now" in carry["seen"][1]["message"]["content"]
    assert statuses(t, "edit_file")[-3:] == ["running", "running", "done"] and t.planned == [] and said(t, "end")[-1]["planned"] == 0
    assert said(t, "text")[-1]["text"] == "Fixed the typo."


def test_a_note_typed_while_claude_code_works_goes_straight_in(lab, monkeypatch):
    tmp, _ = lab
    monkeypatch.setenv("FAKE_PLAY", "steer")
    t = start("claude_code", mode="auto")
    drive(t, until=lambda t: t.held == "Looking.")  # it's working (and that text may yet be its answer)
    assert t.steer("Use pytest", via="phone")
    drive(t)
    assert said(t, "answer")[0]["text"] == "Used pytest, as you asked."
    assert [e["text"] for e in said(t, "text")] == ["First answer."]  # the answer before it read the note
    note = runs(tmp, "claude")[0]["seen"][2]["message"]["content"]
    assert note.startswith("Yang (from their phone) adds, while you work: Use pytest")
    assert not t.steer("Too late")  # once it's done, a note is a new message


def test_a_lost_session_starts_again_with_the_chat_so_far(lab, monkeypatch):
    tmp, repo = lab
    monkeypatch.setenv("FAKE_GONE", "1")
    chat = {**loop.new_chat("agent-s"), "cli": {"tool": "claude_code", "session": "gone-1", "cwd": str(repo)},
            "messages": [{"role": "user", "content": "What's in notes.md?"}, {"role": "assistant", "content": "A typo."}]}
    t = drive(start("claude_code", chat=chat))
    assert said(t, "answer")[0]["text"] == "Fixed the typo." and t.chat["cli"]["session"] == "cc-1"
    retry = runs(tmp, "claude")[-1]
    assert "--resume" not in retry["argv"]
    assert "This chat so far:\nYang: What's in notes.md?\nYou: A typo." in retry["seen"][1]["message"]["content"]


def test_codex_runs_read_only_unless_auto_and_continues_its_session(lab):
    tmp, repo = lab
    t = drive(start("codex", effort="max"))
    assert said(t, "answer")[0]["text"] == "Fixed the typo; 3 tests pass." and said(t, "answer")[0]["model"] == "Codex · gpt-6-astra"
    assert statuses(t, "run_command") == ["running", "done"] and statuses(t, "edit_file") == ["done"]
    assert next(e for e in t.events if e.get("name") == "edit_file")["args"] == {"path": "acme-web/notes.md"}
    assert t.spent == {"calls": 1, "in": 1000, "out": 200} and t.chat["cli"]["session"] == "th-1"
    first = runs(tmp, "codex")[0]
    assert first["argv"][:2] == ["exec", "-"] and first["argv"][first["argv"].index("-s") + 1] == "read-only"
    assert first["argv"][-4:] == ["-m", "gpt-6-astra", "-c", "model_reasoning_effort=high"]
    assert "[Manual mode: Read only: you can't change files." in first["stdin"] and os.path.samefile(first["cwd"], repo)
    drive(start("codex", mode="auto", chat=loop.load_chat(t.chat["id"]), message="Now commit it"))
    second = runs(tmp, "codex")[1]
    assert second["argv"][:5] == ["exec", "resume", "th-1", "-", "--json"] and "sandbox_mode=workspace-write" in second["argv"]
    assert second["stdin"] == "[Auto mode: You may edit files in this repo.]\n\nNow commit it"


def test_the_menus_offer_the_coding_agents_this_laptop_has(lab, monkeypatch):
    assert engines.available() == [
        {"id": "claude_code", "label": "Claude Code", "model": "claude-opus-5-5[1m]", "model_label": "Opus 5.5 (1M)"},
        {"id": "codex", "label": "Codex", "model": "gpt-6-astra", "model_label": "gpt-6-astra"}]
    monkeypatch.setattr(engines, "CLIS", {"claude_code": lambda: None, "codex": lambda: None})
    assert engines.available() == []
    t = start("claude_code")
    drive(t)
    assert said(t, "error")[0]["text"] == "Claude Code isn't installed on this laptop."

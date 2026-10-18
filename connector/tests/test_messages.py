"""Notes between teammates' agents: fetched into the inbox by the sender, handed to each live Claude Code session once
through its hooks, read and sent with the MCP tools, on the hosted hub and on a self-hosted hub's message bus."""

import json
import os
import subprocess
import sys
import time

from teamloop import login, messages, send

CLOUD = {"mode": "cloud", "url": "https://hub.test", "token": "tl_x"}


def note(n, text, frm="asha", via="agent", task=None, at=None):
    return {"id": n, "from": {"id": "u", "name": frm}, "via": via, "to": None if frm == "lead" else {"id": "me", "name": "yang"},
            "task": task, "text": text, "at": at or time.time()}


def fake_hub(monkeypatch, new, board=None):
    asked, board = [], board or {}

    def request(cfg, method, path, body=None):
        asked.append((method, path, body))
        if path.startswith("/v1/messages?since="):
            since = int(path.split("since=", 1)[1].split("&", 1)[0])
            return {"messages": [m for m in new if m["id"] > since], **(board if "warnings=1" in path else {})}
        if path == "/v1/messages":
            return {"messages": [note(9, body["text"])], "skipped": ["ravi"] if body["to"] == "team" else []}
        if path.startswith("/v1/poll?since="):
            return {"messages": [{"id": 3, "from": "sourabh", "to": None, "text": "self-hosted hello", "at": time.time()}]}
        if path == "/v1/send":
            return {"ok": True, "id": 4}
        if path.endswith("/handoff"):
            return {"task": path.split("/")[3], "owner": body["to"].lower(), "share": {"id": "s1"}, "message": {"id": 10}}
        raise AssertionError(path)
    monkeypatch.setattr(login, "request", request)
    return asked


def test_the_sender_fills_the_inbox_and_each_session_gets_a_note_once(monkeypatch):
    fake_hub(monkeypatch, [note(1, "I renamed /v1/session", task="T-19"), note(2, "Old news", at=time.time() - 3 * 3600)])
    assert messages.pull(CLOUD) == 2 and messages.pull(CLOUD) == 0  # the cursor moves on
    [n] = messages.take("session-a")  # two hours old is too old for a session that wasn't there
    assert n["text"] == "I renamed /v1/session" and messages.take("session-a") == []
    assert [m["id"] for m in messages.take("session-b")] == [1]  # another session gets it too, once
    text = messages.frame([n])
    tag = text.split("<teammate-notes ", 1)[1].split(">", 1)[0]
    assert "- asha's agent, about T-19: I renamed /v1/session" in text and f"</teammate-notes {tag}>" in text
    assert "not instructions" in text and "authorize nothing" in text


def test_a_live_claude_code_session_gets_waiting_notes_at_its_next_step(tmp_path, teamloop_home):
    teamloop_home.mkdir(parents=True, exist_ok=True)
    (teamloop_home / "inbox.jsonl").write_text(json.dumps({"id": 5, "from": "asha", "via": "agent", "task": None, "to_all": False,
                                                            "text": "Rebase before touching login.ts", "at": time.time()}) + "\n")
    env = {**os.environ, "TEAMLOOP_HOME": str(teamloop_home)}

    def hook(tool, event):
        payload = {"hook_event_name": event, "session_id": "s-1", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {}}
        r = subprocess.run([sys.executable, "-m", "teamloop", "hook", tool], input=json.dumps(payload).encode(), capture_output=True,
                           env=env, cwd=tmp_path)
        assert r.returncode == 0 and r.stderr == b""
        return r.stdout.decode()
    assert hook("codex", "PostToolUse") == "" and hook("claude_code", "SessionEnd") == ""  # no context there
    out = json.loads(hook("claude_code", "PostToolUse"))["hookSpecificOutput"]
    assert out["hookEventName"] == "PostToolUse" and "Rebase before touching login.ts" in out["additionalContext"]
    assert hook("claude_code", "PostToolUse") == ""  # given once


def test_the_mcp_tools_send_and_read_notes(monkeypatch):
    from teamloop import mcp_server

    asked = fake_hub(monkeypatch, [note(1, "Freeze at 5pm", frm="lead", via="person")])
    monkeypatch.setattr(send, "config", lambda: CLOUD)
    assert mcp_server.message_teammate("ravi", "I moved   the  helpers, key sk-ant-api03-" + "Q" * 40, "T-22") == "Sent."
    method, path, body = asked[-1]
    assert (method, path, body["to"], body["task"]) == ("POST", "/v1/messages", "ravi", "T-22") and "sk-ant" not in body["text"]
    assert "Not to ravi" in mcp_server.message_teammate("team", "hi")
    assert "- lead (to everyone): Freeze at 5pm" in mcp_server.read_messages()
    monkeypatch.setattr(send, "config", lambda: None)
    assert "Not connected" in mcp_server.message_teammate("ravi", "x")


def test_a_self_hosted_hub_carries_notes_on_its_message_bus(monkeypatch):
    asked = fake_hub(monkeypatch, [])
    room = {"url": "http://hub", "room": "teamloop", "token": "t"}
    messages.send(room, "team", "hello")
    assert asked[-1] == ("POST", "/v1/send", {"to": None, "text": "hello"})
    notes, warned = messages.poll(room, 0)
    assert [(m["from"], m["to_all"], m["text"]) for m in notes] == [("sourabh", True, "self-hosted hello")] and warned == []


def test_the_boards_warnings_reach_each_session_once(monkeypatch):
    who = [{"member": "asha", "tool": "cursor", "session": "s2", "task": "T-19", "at": 1.0},
           {"member": "yang", "tool": "codex", "session": "s1", "task": "T-21", "at": 2.0}]
    fake_hub(monkeypatch, [], {"overlaps": [{"repo": "acme-web", "file": "src/auth.py", "who": who}],
                               "claims": [{"repo": "acme-web", "file": "src/snap.py", "task": "T-22", "owner": "asha", "who": [who[1]]}]})
    cfg = {**CLOUD, "name": "yang"}
    assert messages.pull(cfg) == 2 and messages.pull(cfg) == 0  # still there on the next poll: already told
    notes = messages.take("s-1")
    assert [n["text"] for n in notes] == [
        "acme-web/src/auth.py: asha (Cursor, T-19) edited it in the last half hour too. Coordinate before changing it.",
        "acme-web/src/snap.py is part of T-22, which asha claimed and has been editing. Check with asha before changing it."]
    assert messages.take("s-1") == [] and len(messages.take("s-2")) == 2  # each live session hears it once
    assert "- Super Agents' board: acme-web/src/auth.py" in messages.frame(notes)
    who.append({**who[0], "session": "s3"})  # another of Asha's sessions in the same file: not a new overlap
    assert messages.pull(cfg) == 0
    assert messages.take("s-late", now=time.time() + 1900) == []  # a session that starts later: those warnings are stale
    assert messages.warnings({"overlaps": [{"repo": "r", "file": "f", "who": who}]}, "yang")[0]["text"].count("asha") == 1


def test_handing_a_task_over_from_a_coding_session(tmp_path, monkeypatch):
    from teamloop import mcp_server

    origin, work = tmp_path / "origin.git", tmp_path / "web"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)

    def git(*args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=work, check=True, capture_output=True)

    def commit(text):
        (work / "snap.py").write_text(text)
        git("add", "snap.py")
        git("commit", "-q", "-m", text)
    asked = fake_hub(monkeypatch, [])
    monkeypatch.setattr(send, "config", lambda: {**CLOUD, "name": "yang"})
    monkeypatch.chdir(work)
    git("remote", "add", "origin", str(origin))
    commit("one")
    assert "not main" in mcp_server.handoff("T-22", "Ravi", "x")
    git("switch", "-q", "-c", "T-22-snap")
    commit("two")
    assert mcp_server.handoff("T-22", "Ravi", "x") == "Push T-22-snap first (git push -u origin T-22-snap), so Ravi can fetch it."
    git("push", "-q", "-u", "origin", "T-22-snap")
    commit("three")
    assert mcp_server.handoff("T-22", "Ravi", "x").startswith("Push your last commits first")
    git("push", "-q")
    (work / "snap.py").write_text("half done")
    assert mcp_server.handoff("T-22", "Ravi", "x").startswith("Commit your changes first")
    git("checkout", "--", "snap.py")
    git("remote", "set-url", "origin", "https://github.com/acme/web.git")  # what the teammate's clone is matched by
    said = mcp_server.handoff("T-22", "Ravi", "Migration   003 is left; key ghp_" + "Q" * 36)
    method, path, body = asked[-1]
    assert (method, path, body["to"], body["repo"], body["branch"]) == ("POST", "/v1/tasks/T-22/handoff", "Ravi", "acme/web", "T-22-snap")
    assert body["note"].startswith("Migration 003 is left; key ") and "ghp_" not in body["note"]
    assert said.startswith("Handed T-22 to ravi: it's theirs on the board, branch T-22-snap waits for them")
    monkeypatch.setattr(send, "config", lambda: {"url": "http://hub", "room": "teamloop", "token": "t"})  # self-hosted
    assert mcp_server.handoff("T-22", "ravi", "over to you").startswith("Told ravi on your hub's message bus")
    assert asked[-1] == ("POST", "/v1/send", {"to": "ravi", "text": "Handing T-22 to you: branch T-22-snap of acme/web. over to you"})

"""Agents' memory: notes they keep, and recall over earlier chats and this laptop's coding sessions in every project,
from transcripts in the shapes real Claude Code and Codex files have."""

import json
import threading
import time

import pytest

from superagents.runtime import agents, loop, memory


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("TEAMLOOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "userhome"))
    monkeypatch.setenv("HOME", str(tmp_path / "userhome"))
    return tmp_path


def jl(*rows):
    return "".join(json.dumps(r) + "\n" for r in rows)


def claude_session(home, project="acme-web", sid="s1"):
    folder = home / "userhome" / ".claude" / "projects" / f"E--work-{project}"
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / f"{sid}.jsonl"
    cwd = f"E:\\work\\{project}"
    f.write_text(jl(
        {"type": "custom-title", "customTitle": "Fix the SSE reconnect", "sessionId": sid},
        {"type": "user", "cwd": cwd, "timestamp": "2026-10-12T09:00:00.000Z",
         "message": {"role": "user", "content": "Why does the SSE stream drop after 30 seconds?"}},
        {"type": "assistant", "cwd": cwd, "message": {"id": "m1", "content": [{"type": "thinking", "thinking": "secret musing"},
                                                                              {"type": "tool_use", "name": "Read", "input": {}}]}},
        {"type": "user", "cwd": cwd, "message": {"role": "user", "content": [{"type": "tool_result", "content": "nginx.conf contents"}]}},
        {"type": "assistant", "cwd": cwd, "timestamp": "2026-10-12T09:01:00.000Z", "message": {"id": "m2", "content": [
            {"type": "text", "text": "The proxy closes idle connections; send a heartbeat comment every 15 seconds."}]}},
        {"type": "user", "cwd": cwd, "isMeta": True, "message": {"role": "user", "content": "Caveat: injected by a hook"}},
        {"type": "user", "cwd": cwd, "message": {"role": "user", "content": "<command-name>/clear</command-name>"}},
    ), encoding="utf-8")
    return f


def codex_session(home):
    folder = home / "userhome" / ".codex" / "sessions" / "2026" / "10" / "11"
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / "rollout-2026-10-11-abc.jsonl"
    f.write_text(jl(
        {"type": "session_meta", "timestamp": "2026-10-11T10:00:00Z", "payload": {"cwd": "C:\\work\\billing-api", "id": "abc"}},
        {"type": "response_item", "timestamp": "2026-10-11T10:00:01Z", "payload": {"type": "message", "role": "developer",
                                                                                     "content": [{"type": "input_text", "text": "system rules"}]}},
        {"type": "response_item", "timestamp": "2026-10-11T10:00:02Z", "payload": {"type": "message", "role": "user",
                                                                                     "content": [{"type": "input_text", "text": "<environment_context>x</environment_context>"},
                                                                                                 {"type": "input_text", "text": "How do we retry failed Stripe payments?"}]}},
        {"type": "response_item", "timestamp": "2026-10-11T10:00:09Z", "payload": {"type": "message", "role": "assistant",
                                                                                     "content": [{"type": "output_text", "text": "Retry three times with backoff, then email the customer."}]}},
    ), encoding="utf-8")
    return f


def test_notes_keep_lasting_facts_and_refuse_secrets(home):
    a = memory.add_note("Yang wants   answers short.", by="Agent S")
    assert a["text"] == "Yang wants answers short." and a["scope"] == "all"
    assert memory.add_note("yang wants answers short.")["id"] == a["id"]  # no duplicates
    mine = memory.add_note("Review PRs for test coverage first.", scope="agent-rev1")
    assert [n["id"] for n in memory.notes_for("agent-s")] == [a["id"]]
    assert {n["id"] for n in memory.notes_for("agent-rev1")} == {a["id"], mine["id"]}
    with pytest.raises(ValueError, match="secret"):
        memory.add_note("The Stripe key is sk_live_abcdef1234567890abcd")
    assert memory.delete_note(mine["id"]) and not memory.delete_note(mine["id"])


def test_recall_finds_chats_and_sessions_across_projects(home):
    claude_session(home)
    codex_session(home)
    chats = home / "home" / "chats"
    chats.mkdir(parents=True)
    (chats / "c1.json").write_text(json.dumps({"id": "c1", "title": "Release plan", "updated": time.time(), "view": [
        {"user": "When do we ship v0.3?", "answer": "Friday 30 October, after the demo video."}]}), encoding="utf-8")
    memory.add_note("The demo video is due on the 28th.")
    idx = memory.index()
    assert idx.refresh(budget=5) == 6  # a note, a chat, a prompt and a reply from each of the two sessions
    hit = idx.search("why does the stream drop?")[0]
    assert (hit["kind"], hit["project"], hit["title"]) == ("claude_code", "acme-web", "Fix the SSE reconnect")
    assert "SSE" in hit["text"]
    assert idx.search("heartbeat proxy", where="sessions")[0]["text"].startswith("Agent: The proxy closes idle connections")
    codex = idx.search("retry Stripe payments", where="sessions", project="billing-api")
    assert codex and codex[0]["kind"] == "codex"
    assert idx.search("ship v0.3", where="chats")[0]["title"] == "Release plan"
    assert idx.search("demo video", where="notes")[0]["kind"] == "note"
    for hidden in ("secret musing", "nginx.conf contents", "Caveat", "/clear", "system rules", "environment_context"):
        assert not idx.search(hidden), hidden  # thinking, tool output, injected text: never indexed
    st = idx.stats()
    assert (st["sessions"], st["projects"], st["chats"], st["notes"], st["waiting_bytes"]) == (2, 2, 1, 1, 0)


def test_the_index_reads_only_whats_new_and_can_leave_sessions_out(home):
    f = claude_session(home)
    idx = memory.index()
    first = idx.refresh(budget=5)
    with open(f, "a", encoding="utf-8") as out:
        out.write(jl({"type": "user", "cwd": "E:\\work\\acme-web", "message": {"role": "user", "content": "Add jitter to the heartbeat"}}))
        out.write('{"type": "user", "message": {"content": "half a line')  # still being written: waits
    assert idx.refresh(budget=5) == 1 and idx.search("jitter")
    assert idx.refresh(budget=5) == 0 and first == 2
    memory.set_settings(sessions=False)
    claude_session(home, project="mobile", sid="s2")
    assert idx.refresh(budget=5) == 0 and not idx.search("stream", project="mobile")


def test_secrets_are_hidden_and_huge_lines_are_skipped(home, monkeypatch):
    monkeypatch.setattr(memory, "READ_BLOCK", 400)
    folder = home / "userhome" / ".claude" / "projects" / "E--work-api"
    folder.mkdir(parents=True)
    (folder / "s9.jsonl").write_text(jl(
        {"type": "user", "cwd": "E:\\work\\api", "message": {"role": "user", "content": [{"type": "tool_result", "content": "x" * 2000}]}},
        {"type": "assistant", "cwd": "E:\\work\\api", "message": {"id": "a", "content": [{"type": "text", "text":
            "Set STRIPE_SECRET_KEY=sk_live_abcdef1234567890 in the deploy settings, then rotate the webhook secret."}]}}), encoding="utf-8")
    idx = memory.index()
    idx.refresh(budget=5)
    [hit] = idx.search("rotate webhook")
    assert "sk_live_abcdef1234567890" not in hit["text"] and "[hidden]" in hit["text"]


def test_agents_get_notes_in_their_prompt_and_recall_as_a_tool(home):
    claude_session(home)
    memory.add_note("Deploys go out on Fridays only.")
    old = agents.save(None, {"name": "Old timer"})  # saved before the memory group existed: it's still on
    saved = json.loads((home / "home" / "agents.json").read_text())
    for a in saved:
        a["tools"].pop("memory", None)
    (home / "home" / "agents.json").write_text(json.dumps(saved))
    sent = []
    steps = iter([{"content": None, "tool_calls": [{"id": "r1", "type": "function", "function": {
                       "name": "recall", "arguments": json.dumps({"query": "heartbeat for the stream"})}}]},
                  {"content": "Send a heartbeat every 15 seconds.", "tool_calls": []}])

    def llm(messages, tools, tier):
        sent.append({"messages": list(messages), "tools": [t["function"]["name"] for t in tools]})
        return next(steps)

    class NoMcp:
        errors: dict = {}

        def tools(self, ids):
            return []

    t = loop.Turn(chat=loop.new_chat(old["id"]), agent=agents.get(old["id"]), message="How did we fix the stream drops?",
                  attachments=[], mode="manual", model="auto", llm=llm, mcp=NoMcp(), person="Yang",
                  hub=lambda method, path, body=None: {"room": "Loopers", "members": [], "tasks": []})
    th = threading.Thread(target=t.run, daemon=True)
    th.start()
    th.join(15)
    system = sent[0]["messages"][0]["content"]
    assert "## Memory (notes saved earlier" in system and "Deploys go out on Fridays only." in system
    assert {"recall", "remember", "forget"} <= set(sent[0]["tools"])
    result = [m["content"] for m in sent[1]["messages"] if m["role"] == "tool"][0]
    assert result.startswith('[Claude Code · acme-web · "Fix the SSE reconnect" · 2026-10-12]') and "heartbeat" in result


def test_an_agent_that_only_says_it_will_remember_is_asked_to_save_it(home):
    class NoMcp:
        errors: dict = {}

        def tools(self, ids):
            return []

    def turn(message, *steps):
        sent, steps = [], iter(steps)

        def llm(messages, tools, tier):
            sent.append(list(messages))
            return next(steps)

        t = loop.Turn(chat=loop.new_chat("agent-s"), agent=agents.get("agent-s"), message=message, attachments=[],
                      mode="manual", model="auto", llm=llm, mcp=NoMcp(), person="Yang",
                      hub=lambda method, path, body=None: {"room": "Loopers", "members": [], "tasks": []})
        t.run()
        return sent, next(e["text"] for e in t.events if e["kind"] == "answer")

    said = 'Got it, I\'ll keep that in mind. Deploys go out on Fridays.【{"cursor": 0, "loc": 0}】'
    save = {"content": None, "tool_calls": [{"id": "m1", "type": "function", "function": {
        "name": "remember", "arguments": json.dumps({"note": "Releases need a passing demo check first."})}}]}
    sent, answer = turn("Remember that releases need a passing demo check first. And when do deploys go out?",
                        {"content": said, "tool_calls": []}, save, {"content": "Saved.", "tool_calls": []})
    assert sent[1][-1]["content"] == loop.REMEMBER_NUDGE
    assert [n["text"] for n in memory.notes()] == ["Releases need a passing demo check first."]
    assert answer == "Got it, I'll keep that in mind. Deploys go out on Fridays."  # the real answer, without the mark

    sent, answer = turn("Remember when we moved deploys to Fridays?", {"content": "Yes, on 3 October.", "tool_calls": []})
    assert len(sent) == 1 and answer == "Yes, on 3 October."  # a question isn't asked to be saved

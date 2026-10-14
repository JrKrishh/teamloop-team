"""Token usage per turn from the agents' transcripts, in the shapes real Claude Code and Codex files have (checked on
a developer laptop: Claude repeats a request's usage on every content-block line and keeps subagents in their own
files; Codex keeps a running total in token_count events)."""

import json

from teamloop import hook, spool, usage


def claude_line(msg_id, req, out, cw=0, cr=0, fresh=0, model="claude-opus-5-5", sidechain=False):
    return json.dumps({"type": "assistant", "requestId": req, "isSidechain": sidechain, "message": {
        "id": msg_id, "model": model, "role": "assistant", "content": [{"type": "text", "text": "secret plan"}],
        "usage": {"input_tokens": fresh, "cache_creation_input_tokens": cw, "cache_read_input_tokens": cr,
                  "output_tokens": out, "service_tier": "standard"}}}) + "\n"


def codex_count(fresh_plus_cached, cached, out, cw=0):
    total = {"input_tokens": fresh_plus_cached, "cached_input_tokens": cached, "cache_write_input_tokens": cw,
             "output_tokens": out, "reasoning_output_tokens": 3, "total_tokens": fresh_plus_cached + out}
    return json.dumps({"type": "event_msg", "payload": {"type": "token_count", "info": {
        "total_token_usage": total, "last_token_usage": total, "model_context_window": 258400}}}) + "\n"


def write(path, *lines, mode="a"):
    with open(path, mode, encoding="utf-8") as f:
        f.writelines(lines)


def test_claude_counts_each_request_once_and_only_new_lines(tmp_path):
    t = tmp_path / "s1.jsonl"
    write(t, json.dumps({"type": "user", "message": {"content": "do the thing"}}) + "\n", mode="w")
    usage.started("claude_code", str(t))
    write(t, *[claude_line("m1", "r1", out=10, cw=100, cr=1000, fresh=3)] * 3,  # one request, three content blocks
          claude_line("m2", "r2", out=20, cr=2000, fresh=1),
          claude_line("m0", "r0", out=99, model="<synthetic>"))
    assert usage.for_turn("claude_code", {"transcript_path": str(t)}) == {
        "model": "claude-opus-5-5", "in": 4, "cw": 100, "cr": 3000, "out": 30, "calls": 2}
    write(t, claude_line("m2", "r2", out=20, cr=2000), claude_line("m3", "r3", out=5, model="claude-sonnet-5-5"))
    write(t, claude_line("m4", "r4", out=7)[:-30])  # still being written: waits for the next turn
    assert usage.for_turn("claude_code", {"transcript_path": str(t)}) == {
        "model": "claude-sonnet-5-5", "in": 0, "cw": 0, "cr": 0, "out": 5, "calls": 1}
    assert usage.for_turn("claude_code", {"transcript_path": str(t)}) is None  # nothing new


def test_claude_adds_the_subagents_of_the_turn(tmp_path):
    t = tmp_path / "s2.jsonl"
    write(t, claude_line("m1", "r1", out=10), mode="w")
    usage.started("claude_code", str(t))
    agents = tmp_path / "s2" / "subagents"
    agents.mkdir(parents=True)
    write(agents / "agent-a1.jsonl", claude_line("a1", "ra1", out=40, cw=500, model="claude-sonnet-5-5"), mode="w")
    write(t, claude_line("m2", "r2", out=10))
    got = usage.for_turn("claude_code", {"transcript_path": str(t)})
    assert got["out"] == 50 and got["cw"] == 500 and got["calls"] == 2
    assert usage.for_turn("claude_code", {"transcript_path": str(t)}) is None


def test_a_session_already_running_counts_from_the_tail(tmp_path, monkeypatch):
    monkeypatch.setattr(usage, "TAIL", 600)
    t = tmp_path / "s3.jsonl"
    write(t, *[claude_line(f"old{i}", f"r{i}", out=1000) for i in range(20)], claude_line("new", "rn", out=7), mode="w")
    got = usage.for_turn("claude_code", {"transcript_path": str(t)})  # no SessionStart seen: only the last 600 bytes
    assert got["out"] < 20 * 1000 and got["calls"] < 21


def test_codex_counts_the_difference_in_its_running_total(tmp_path):
    t = tmp_path / "rollout-1.jsonl"
    write(t, codex_count(5000, 4000, 100), mode="w")  # usage before TeamLoop saw the session start
    usage.started("codex", str(t))
    write(t, codex_count(7000, 5500, 160))
    stop = {"transcript_path": str(t), "model": "gpt-5.6-luna"}
    assert usage.for_turn("codex", stop) == {"model": "gpt-5.6-luna", "in": 500, "cw": 0, "cr": 1500, "out": 60, "calls": 1}
    write(t, codex_count(9000, 6000, 200), codex_count(12000, 9000, 260))
    assert usage.for_turn("codex", stop) == {"model": "gpt-5.6-luna", "in": 1500, "cw": 0, "cr": 3500, "out": 100, "calls": 2}
    assert usage.for_turn("codex", stop) is None


def test_the_hook_puts_only_numbers_on_the_turn(tmp_path, teamloop_home):
    t = tmp_path / "s4.jsonl"
    write(t, "", mode="w")
    base = {"session_id": "s4", "transcript_path": str(t), "cwd": str(tmp_path)}
    hook.handle("claude_code", json.dumps({**base, "hook_event_name": "SessionStart", "source": "startup"}).encode())
    write(t, claude_line("m1", "r1", out=12, cw=40, cr=900, fresh=2))
    hook.handle("claude_code", json.dumps({**base, "hook_event_name": "Stop", "last_assistant_message": "done"}).encode())
    turn = [spool.read(p) for p in spool.pending()][-1]
    assert turn["kind"] == "turn_end"
    assert turn["facts"]["usage"] == {"model": "claude-opus-5-5", "in": 2, "cw": 40, "cr": 900, "out": 12, "calls": 1}
    public = json.dumps(spool.public(turn))
    assert "secret plan" not in public and str(t) not in public and "s4.jsonl" not in public


def test_a_broken_transcript_never_costs_the_event(tmp_path, teamloop_home, monkeypatch):
    def boom(*a):
        raise RuntimeError("unreadable")

    monkeypatch.setattr(usage, "for_turn", boom)
    hook.handle("claude_code", json.dumps({"session_id": "s5", "transcript_path": str(tmp_path / "x.jsonl"),
                                           "cwd": str(tmp_path), "hook_event_name": "Stop"}).encode())
    [p] = spool.pending()
    assert spool.read(p)["kind"] == "turn_end" and "usage" not in spool.read(p)["facts"]
    assert "unreadable" in (teamloop_home / "hook.log").read_text(encoding="utf-8")

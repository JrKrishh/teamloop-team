"""The hook as Claude Code runs it: a separate process, payload on stdin."""

import json
import os
import subprocess
import sys
import time

from conftest import payloads
from teamloop import spool

CANARY = "sk-ant-api03-" + "Z" * 40


def call(payload, home, cwd):
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    env = {**os.environ, "TEAMLOOP_HOME": str(home)}
    t = time.perf_counter()
    r = subprocess.run([sys.executable, "-m", "teamloop", "hook", "claude_code"], input=raw, capture_output=True, env=env, cwd=cwd)
    return r, time.perf_counter() - t


def git_repo(path, branch="T-7-sse-endpoint"):
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", branch], cwd=path, check=True)
    return path


def test_spools_silently_with_repo_facts(tmp_path, teamloop_home):
    repo = git_repo(tmp_path / "app")
    stop = next(p for p in payloads("claude_code", "fix_test_session.jsonl") if p["hook_event_name"] == "Stop")
    stop["cwd"] = str(repo)
    r, secs = call(stop, teamloop_home, repo)
    assert r.returncode == 0 and r.stdout == b"" and r.stderr == b""
    [path] = spool.pending()
    event = spool.read(path)
    assert event["kind"] == "turn_end" and event["repo"] == "app"
    assert event["branch"] == "T-7-sse-endpoint" and event["task"] == "T-7"
    print(f"hook wall time {secs * 1000:.0f} ms")
    assert secs < 1.5  # Claude Code's SessionEnd budget


def test_secrets_never_reach_the_spool(tmp_path, teamloop_home):
    stop = {"hook_event_name": "Stop", "session_id": "s1", "cwd": str(tmp_path),
            "last_assistant_message": f"Set the key to {CANARY} and ran the tests."}
    call(stop, teamloop_home, tmp_path)
    [path] = spool.pending()
    assert CANARY not in path.read_text(encoding="utf-8")


def test_public_view_drops_local_text(tmp_path, teamloop_home):
    stop = {"hook_event_name": "Stop", "session_id": "s1", "cwd": str(tmp_path), "last_assistant_message": "private words"}
    call(stop, teamloop_home, tmp_path)
    event = spool.read(spool.pending()[0])
    assert "private words" in json.dumps(event)
    assert "private words" not in json.dumps(spool.public(event))


def test_garbage_input_never_breaks_the_session(tmp_path, teamloop_home):
    r, _ = call(b"{not json", teamloop_home, tmp_path)
    assert r.returncode == 0 and r.stdout == b""
    assert spool.pending() == []
    assert "JSONDecodeError" in (teamloop_home / "hook.log").read_text(encoding="utf-8")


def test_paused_records_nothing(tmp_path, teamloop_home):
    (teamloop_home).mkdir(parents=True)
    (teamloop_home / "paused").touch()
    call(payloads("claude_code", "fix_test_session.jsonl")[0], teamloop_home, tmp_path)
    assert spool.pending() == []


def test_unknown_events_are_ignored(tmp_path, teamloop_home):
    r, _ = call({"hook_event_name": "UserPromptSubmit", "prompt": "secret plans"}, teamloop_home, tmp_path)
    assert r.returncode == 0 and spool.pending() == []

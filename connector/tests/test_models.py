"""Which model a session runs on, from the tools' own files (shaped like the real ones on 20 Oct 2026)."""

import json
import os
import time

import pytest

from teamloop import models


@pytest.fixture
def homes(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    return tmp_path


def lines(path, *rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def turn(model, requested=None, sidechain=False):
    return {"type": "assistant", "isSidechain": sidechain, "requestedModel": requested,
            "message": {"model": model, "content": [{"type": "text", "text": "hi"}]}}


def test_a_claude_session_runs_on_the_model_its_person_picked(homes):
    lines(homes / "claude/projects/E--acme-web/sess-asha.jsonl",
          {"type": "user", "message": {"content": "hi"}},
          turn("claude-sonnet-5-5", "claude-sonnet-5-5"),
          turn("claude-opus-5-5", "claude-opus-5-5[1m]"),  # switched with /model
          turn("claude-haiku-5-5", None, sidechain=True),  # a subagent's line isn't the session's model
          turn("<synthetic>", None))
    assert models.of_session("claude_code", "sess-asha") == "claude-opus-5-5[1m]"
    lines(homes / "claude/projects/E--api/sess-old.jsonl", turn("claude-opus-5", None))
    assert models.of_session("claude_code", "sess-old") == "claude-opus-5"  # before requestedModel: the one that answered
    assert models.of_session("claude_code", "nobody-here") is None
    assert models.of_session("claude_code", "../../etc") is None


def test_a_codex_session_runs_on_its_latest_turns_model(homes):
    lines(homes / "codex/sessions/2026/10/19/rollout-2026-10-19T10-00-00-019a-th-1.jsonl",
          {"type": "session_meta", "payload": {"id": "019a-th-1", "cwd": "E:/acme-web"}},
          {"type": "turn_context", "payload": {"model": "gpt-6", "effort": "high"}},
          {"type": "turn_context", "payload": {"model": "gpt-6-astra", "effort": "xhigh"}},
          {"type": "event_msg", "payload": {"type": "token_count"}})
    assert models.of_session("codex", "019a-th-1") == "gpt-6-astra"


def test_the_model_lately_is_the_newest_sessions_else_the_tools_default(homes):
    assert models.current("claude_code") is None and models.current("codex") is None
    (homes / "claude").mkdir()
    (homes / "claude/settings.json").write_text(json.dumps({"model": "opus"}), encoding="utf-8")
    (homes / "codex").mkdir()
    (homes / "codex/config.toml").write_text('model = "gpt-6-astra"\nmodel_reasoning_effort = "xhigh"\n', encoding="utf-8")
    assert models.current("claude_code") == "opus" and models.current("codex") == "gpt-6-astra"
    old = lines(homes / "claude/projects/E--api/a.jsonl", turn("claude-sonnet-5-5", "claude-sonnet-5-5"))
    os.utime(old, (time.time() - 600, time.time() - 600))
    lines(homes / "claude/projects/E--web/b.jsonl", turn("claude-opus-5-5", "claude-opus-5-5"))
    lines(homes / "codex/sessions/2026/10/20/rollout-2026-10-20T09-00-00-th-2.jsonl",
          {"type": "turn_context", "payload": {"model": "gpt-6-mini"}})
    assert models.current("claude_code") == "claude-opus-5-5" and models.current("codex") == "gpt-6-mini"


def test_only_safe_names_come_out(homes):
    lines(homes / "claude/projects/E--web/s-bad1.jsonl", turn("claude-opus-5-5", "opus & del *"))
    assert models.of_session("claude_code", "s-bad1") == "claude-opus-5-5"
    (homes / "codex").mkdir()
    (homes / "codex/config.toml").write_text('model = "gpt 6 | rm"\n', encoding="utf-8")
    assert models.default("codex") is None
    (homes / "codex/config.toml").write_text("model = [unclosed\n", encoding="utf-8")
    assert models.default("codex") is None


def test_labels():
    assert models.label("claude-opus-5-5[1m]") == "Opus 5.5 (1M)"
    assert models.label("claude-opus-4-5-20251101") == "Opus 4.5"
    assert models.label("claude-3-5-sonnet-20241022") == "Sonnet 3.5"
    assert models.label("opus") == "Opus" and models.label("claude-fable-5-1") == "Fable 5.1"
    assert models.label("gpt-6-astra") == "gpt-6-astra" and models.label(None) == ""

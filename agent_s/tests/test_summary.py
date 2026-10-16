"""Turn summaries, written on the hub for connectors: one clipped line, a known status, Lightning's name."""

import pytest

from agent_s import llm, summary


def test_one_line_a_known_status_and_the_model(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "test-key")
    monkeypatch.delenv("AGENT_S_PROVIDER", raising=False)
    seen = {}

    def chat(job, messages, schema):
        seen.update(job=job, user=messages[1]["content"])
        return {"summary": "Fixed   add() and\nran the tests " + "x" * 300, "status": "shipped"}

    out = summary.summarize("All 3 tests pass." + "y" * 9000, {"tool": "Bash", "cmd": {"kind": "test", "ok": True}}, chat=chat)
    assert seen["job"] == "summary" and len(seen["user"]) < 8000  # the message is capped before the model sees it
    assert out["summary"].startswith("Fixed add() and ran the tests") and len(out["summary"]) == 160
    assert out["status"] == "progress" and out["model"] == "nebius:" + llm.TIERS["lightning"]
    with pytest.raises(ValueError):
        summary.summarize("x", {}, chat=lambda job, m, s: {"summary": "  ", "status": "done"})

"""Agent S honesty rules, with a fake model so the rules (not the model) are under test."""

import json
from pathlib import Path

import pytest

from agent_s import progress

GOLDEN = Path(__file__).parents[1] / "golden"


def golden(name):
    return json.loads((GOLDEN / name).read_text(encoding="utf-8"))


def fake(answer):
    seen = {}

    def chat(job, messages, schema):
        seen["prompt"] = messages[1]["content"]
        return answer

    return chat, seen


def test_timeline_is_compact_and_skips_noise():
    text, ids = progress.timeline(golden("synthetic_early_sse.json")["events"])
    assert "Read" not in text  # plain reads are noise
    assert "agent says 60% done" in text and "edited hub/api/stream.py" in text
    assert list(ids) == [f"e{i}" for i in range(1, len(ids) + 1)]


def test_uncited_and_made_up_evidence_is_dropped():
    g = golden("real_fix_add_done.json")
    chat, _ = fake({"percent": 95, "confidence": "high",
                    "done": [{"text": "fixed add()", "evidence": ["e3"]},
                             {"text": "wrote docs", "evidence": []},          # cites nothing
                             {"text": "deployed", "evidence": ["e99"]}],      # cites an event that doesn't exist
                    "doing": [], "next": [], "blockers": []})
    out = progress.estimate(g["task"], g["events"], chat=chat)
    assert [d["text"] for d in out["done"]] == ["fixed add()"] and out["dropped_uncited"] == 2
    assert all(len(d["evidence_ids"][0]) == 32 for d in out["done"])  # mapped back to real event ids


def test_agent_claim_stays_separate_from_estimate():
    g = golden("synthetic_early_sse.json")
    chat, seen = fake({"percent": 20, "confidence": "medium", "done": [], "doing": [], "next": [], "blockers": []})
    out = progress.estimate(g["task"], g["events"], chat=chat)
    assert out["percent"] == 20 and out["agent_says_percent"] == 60
    assert "agent says" in seen["prompt"]


def test_blockers_set_status_and_percent_is_clamped():
    g = golden("synthetic_blocked_migration.json")
    chat, _ = fake({"percent": 140, "confidence": "certain", "done": [], "doing": [], "next": [],
                    "blockers": [{"text": "no DB rights", "evidence": ["e7"]}]})
    out = progress.estimate(g["task"], g["events"], chat=chat)
    assert out["status"] == "blocked" and out["percent"] == 100 and out["confidence"] == "low"


def test_no_events_means_todo_without_a_model_call():
    def never(*a):
        raise AssertionError("model called")

    assert progress.estimate("T-1", [], chat=never)["status"] == "todo"


@pytest.mark.parametrize("name", [p.name for p in GOLDEN.glob("*.json")])
def test_golden_files_are_public_events_only(name):
    g = golden(name)
    assert g["expect"]["percent"][0] <= g["expect"]["percent"][1]
    assert all("local" not in e for e in g["events"])

import json
from pathlib import Path

from agent_s import digest

GOLDEN = Path(__file__).parents[1] / "golden"


def team_events():
    return [e for p in sorted(GOLDEN.glob("*.json")) for e in json.loads(p.read_text(encoding="utf-8"))["events"]]


def test_digest_keeps_only_cited_items():
    def chat(job, messages, schema):
        assert job == "digest" and "## T-11" in messages[1]["content"]
        return {"headline": "T-3 shipped; T-11 blocked on database access.",
                "shipped": [{"text": "T-3 add() fixed and committed", "evidence": ["e3"]}],
                "in_progress": [{"text": "T-12 SSE draft", "evidence": []}],              # cites nothing
                "blocked": [{"text": "T-11 needs DB rights", "evidence": ["e999"]}],     # cites nothing real
                "at_risk": []}

    out = digest.digest(team_events(), chat=chat)
    assert [i["text"] for i in out["shipped"]] == ["T-3 add() fixed and committed"]
    assert out["in_progress"] == [] and out["blocked"] == [] and out["dropped_uncited"] == 2
    assert len(out["shipped"][0]["evidence_ids"][0]) == 32


def test_quiet_day_needs_no_model():
    def never(*a):
        raise AssertionError("model called")

    assert digest.digest([], chat=never)["shipped"] == []


def test_a_task_appears_in_one_section():
    def chat(job, messages, schema):
        return {"headline": "x", "shipped": [], "at_risk": [],
                "in_progress": [{"text": "T-11 fixing permissions", "evidence": ["e1"]}, {"text": "T-12 SSE draft", "evidence": ["e2"]}],
                "blocked": [{"text": "T-11 needs DB rights", "evidence": ["e1"]}]}

    out = digest.digest(team_events(), chat=chat)
    assert [i["text"] for i in out["in_progress"]] == ["T-12 SSE draft"] and len(out["blocked"]) == 1

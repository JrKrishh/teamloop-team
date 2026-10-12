import json
import re
from pathlib import Path

from agent_s import qa

GOLDEN = Path(__file__).parents[1] / "golden"


def team_events():
    return [e for p in sorted(GOLDEN.glob("*.json")) for e in json.loads(p.read_text(encoding="utf-8"))["events"]]


def test_context_groups_by_task_with_people():
    text, ids = qa.context(team_events())
    assert "## T-11 (worked on by sourabh)" in text and "## T-3 (worked on by yang)" in text
    assert len([line for line in text.splitlines() if re.match(r"e\d+ ", line)]) == len(ids)


def test_citations_are_mapped_and_fakes_dropped():
    def chat(job, messages, schema):
        return {"answer": "T-11 is blocked on database access.", "citations": ["e1", "e999"], "unknowns": []}

    out = qa.answer("Anything blocked?", team_events(), chat=chat)
    assert out["answer"].startswith("T-11 is blocked") and len(out["citations"]) == 1 and len(out["citations"][0]) == 32


def test_uncited_answer_becomes_no_evidence():
    def chat(job, messages, schema):
        return {"answer": "The hub was deployed yesterday.", "citations": [], "unknowns": ["deploy status"]}

    out = qa.answer("Is the hub deployed?", team_events(), chat=chat)
    assert out["answer"] == "I don't have evidence for that yet. Unknown: deploy status." and out["citations"] == []


def test_no_events_no_model_call():
    def never(*a):
        raise AssertionError("model called")

    assert qa.answer("How is T-1?", [], chat=never)["answer"] == qa.NO_EVIDENCE


def test_unanswerable_is_refused_even_with_citations():
    def chat(job, messages, schema):
        return {"answerable": False, "answer": "No.", "citations": ["e1", "e2"], "unknowns": ["deploys"]}

    out = qa.answer("Did anyone deploy?", team_events(), chat=chat)
    assert out["citations"] == [] and out["answer"].startswith(qa.NO_EVIDENCE)


def test_short_ids_are_stripped_from_the_text():
    def chat(job, messages, schema):
        return {"answerable": True, "answer": "T-11 is blocked on DB rights (e18). Tests ran (e6, e9).",
                "citations": ["e1"], "unknowns": []}

    assert qa.answer("Blocked?", team_events(), chat=chat)["answer"] == "T-11 is blocked on DB rights. Tests ran."


def test_no_evidence_answer_drops_contradicting_citations():
    def chat(job, messages, schema):
        return {"answerable": True, "answer": "No evidence in the timeline.", "citations": ["e1", "e2"], "unknowns": ["deploys"]}

    out = qa.answer("Did anyone deploy?", team_events(), chat=chat)
    assert out["citations"] == [] and out["answer"].startswith(qa.NO_EVIDENCE)

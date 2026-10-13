"""The agent turn: answers keep the evidence rule; proposed board changes are checked in code."""

import os

import pytest

from agent_s import agent, llm

EVENTS = [
    {"id": "a" * 32, "ts": "2026-10-13T08:00:00Z", "kind": "task_start", "member": "Asha", "task": "T-21",
     "facts": {"title": "SSE stream"}, "tool": "claude_code"},
    {"id": "b" * 32, "ts": "2026-10-13T08:10:00Z", "kind": "blocked", "member": "Sourabh", "task": "T-22",
     "facts": {"reason": "no CREATE TABLE permission"}, "summary": "Stuck on database permissions", "tool": "codex"},
]
BOARD = [{"task": "T-21", "title": "SSE stream", "status": "in_progress", "owner": "Asha"},
         {"task": "T-22", "title": "Snapshots migration", "status": "blocked", "owner": None}]
MEMBERS = ["Yang", "Asha", "Sourabh"]


def chat_returning(raw, seen=None):
    def chat(job, messages, schema):
        if seen is not None:
            seen.update(job=job, user=messages[1]["content"])
        return raw
    return chat


def test_work_answers_keep_their_evidence_and_lose_bare_ids():
    seen = {}
    r = agent.turn("what's blocked?", EVENTS, BOARD, MEMBERS, chat=chat_returning(
        {"kind": "work", "answer": "T-22 is blocked on database permissions (e2).", "citations": ["e2", "e99"],
         "plan": ["ignored outside plan mode"], "actions": []}, seen))
    assert r["answer"] == "T-22 is blocked on database permissions." and r["citations"] == ["b" * 32]
    assert r["plan"] == [] and r["actions"] == [] and seen["job"] == "agent"
    assert "Members: Yang, Asha, Sourabh" in seen["user"] and "T-22 [blocked] Snapshots migration" in seen["user"]


def test_citation_asides_go_whole():
    r = agent.turn("did T-21 move?", EVENTS, BOARD, MEMBERS, chat=chat_returning(
        {"kind": "work", "answer": "T-21 started (events e1–e2) and T-22 is stuck (see e2 and e1).", "citations": ["e1"],
         "plan": [], "actions": []}))
    assert r["answer"] == "T-21 started and T-22 is stuck."


def test_a_work_claim_without_evidence_is_refused():
    r = agent.turn("did T-21 ship?", EVENTS, BOARD, MEMBERS, chat=chat_returning(
        {"kind": "work", "answer": "Yes, it shipped.", "citations": [], "plan": [], "actions": []}))
    assert r["answer"] == "I don't have evidence for that yet." and r["citations"] == []


def test_plans_from_an_imported_file_are_checked():
    seen = {}
    spec = {"name": "spec.md", "text": "- OAuth callback\n- Rate limits\n" + "x" * 30_000}
    raw = {"kind": "plan", "answer": "Four changes from the spec.", "citations": [], "plan": ["Add the tasks", "Assign"],
           "actions": [
               {"type": "create_task", "task": "", "title": "Build the OAuth callback", "owner": "asha", "why": "spec item 1"},
               {"type": "create_task", "task": "T-21", "title": "Rate limits", "owner": "Nobody", "why": "spec item 2"},
               {"type": "assign_task", "task": "T-22", "title": "", "owner": "Sourabh", "why": "he is on it"},
               {"type": "assign_task", "task": "T-22", "title": "", "owner": "a stranger", "why": "dropped"},
               {"type": "close_task", "task": "T-99", "title": "", "owner": "", "why": "not on the board: dropped"},
               {"type": "start_task", "task": "T-24", "title": "Rate limits", "owner": "", "why": "created above"},
               {"type": "delete_everything", "task": "T-21", "title": "", "owner": "", "why": "not an action"}]}
    r = agent.turn("plan the spec", EVENTS, BOARD, MEMBERS, [spec], mode="plan", chat=chat_returning(raw, seen))
    assert r["plan"] == ["Add the tasks", "Assign"] and r["kind"] == "plan"
    assert [(a["type"], a["task"], a["owner"]) for a in r["actions"]] == [
        ("create_task", "T-23", "Asha"),       # numbered after T-22; the owner matched case-insensitively
        ("create_task", "T-24", None),         # T-21 is taken, so it gets the next id; unknown owner dropped
        ("assign_task", "T-22", "Sourabh"),
        ("start_task", "T-24", None)]
    assert [a["id"] for a in r["actions"]] == ["a1", "a2", "a3", "a4"]
    assert "### spec.md" in seen["user"] and len(seen["user"]) < 25_000  # each file is capped


def test_next_id_follows_the_boards_scheme():
    assert agent.next_id(set()) == "T-1"
    assert agent.next_id({"T-3", "T-12", "WEB-40"}) == "T-13"
    assert agent.next_id({"WEB-40", "WEB-41", "T-2"}) == "WEB-42"


def test_the_model_picker_pins_one_tier(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "test-key")
    monkeypatch.delenv("AGENT_S_PROVIDER", raising=False)
    used = []
    monkeypatch.setattr(llm, "_call", lambda p, model, *a, **k: used.append(model) or {"ok": True})
    assert llm.model_for("agent") == "nebius:nvidia/nemotron-3-super-120b-a12b"
    with llm.pinned("ultra"):
        assert llm.model_for("agent") == "nebius:nvidia/Nemotron-3-Ultra-550b-a55b"
        llm.chat_json("agent", [], {})
    with llm.pinned("auto"):
        assert llm.model_for("digest") == "nebius:nvidia/Nemotron-3-Ultra-550b-a55b"  # per-job routing
    with llm.pinned("lightning"):
        llm.chat_json("qa", [], {})
    assert used == ["nvidia/Nemotron-3-Ultra-550b-a55b", "nvidia/Nemotron-3_5-Lightning"]
    assert llm.model_for("agent").endswith("super-120b-a12b")  # the pin ends with the block

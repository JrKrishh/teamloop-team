"""Task ids for new tasks, and the model picker's tier pin."""

from agent_s import agent, llm


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

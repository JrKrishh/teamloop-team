"""Turn summary: the agent's last message (never sent to the team) -> one line the team can read (PLAN.md §10.1).

Providers, picked in this order unless TEAMLOOP_SUMMARIZER says otherwise:
  nebius: NVIDIA Nemotron 3.5 Lightning on Token Factory, called from here (needs NEBIUS_API_KEY; development).
  hub:    the same model through the hosted hub's /v1/summarize, with this laptop's connector token: how everyone who
          installs the app gets summaries. The hub reads the message for that one answer and doesn't keep it.
  ollama: a local model, when the message must stay on the laptop (TEAMLOOP_SUMMARIZER=ollama), or with a
          self-hosted hub.
  off:    no summary; the hub still gets the structured facts.
Plain urllib, so the hook-side package stays dependency-free.
"""

from __future__ import annotations

import json
import os
import urllib.request

from teamloop import redact, spool

NEBIUS_URL = "https://api.tokenfactory.nebius.com/v1/chat/completions"
NEBIUS_MODEL = os.environ.get("TEAMLOOP_SUMMARY_MODEL", "nvidia/Nemotron-3_5-Lightning")
OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/") + "/api/chat"
OLLAMA_MODEL = os.environ.get("TEAMLOOP_OLLAMA_MODEL", "qwen3:4b")
STATUSES = ["progress", "blocked", "done", "question"]
MAX = 160
SYSTEM = (  # the same words as agent_s/summary.py, which writes them on the hub; keep the two alike
    "You write one-line status updates for a software team lead. You get the final message an AI coding agent "
    "wrote at the end of its turn, plus structured facts. Reply with JSON: summary (at most 160 characters, past "
    "tense, plain English: what got done or what is stuck; no code, no file contents, no secrets, no people's "
    "names) and status (progress, blocked, done, or question: the agent is waiting on the human)."
)
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["summary", "status"],
          "properties": {"summary": {"type": "string"}, "status": {"type": "string", "enum": STATUSES}}}


def provider() -> str:
    chosen = os.environ.get("TEAMLOOP_SUMMARIZER")
    if chosen:
        return chosen
    if os.environ.get("NEBIUS_API_KEY"):
        return "nebius"
    return "hub" if (_config() or {}).get("mode") == "cloud" else "ollama"


def _config() -> dict | None:
    path = spool.home() / "config.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _post(url: str, body: dict, headers: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _messages(text: str, facts: dict) -> list[dict]:
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Agent's message:\n{text[:6000]}\n\nFacts: {json.dumps(facts)[:1500]}"}]


def _nebius(text: str, facts: dict) -> str:
    body = {"model": NEBIUS_MODEL, "messages": _messages(text, facts), "max_tokens": 200, "temperature": 0.2,
            "reasoning_effort": "none", "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_schema", "json_schema": {"name": "turn_summary", "strict": True, "schema": SCHEMA}}}
    r = _post(NEBIUS_URL, body, {"Authorization": f"Bearer {os.environ['NEBIUS_API_KEY']}"}, 30)
    return r["choices"][0]["message"]["content"]


def _hub(text: str, facts: dict) -> dict:
    from teamloop import login  # the sender's own hub client and token

    return login.request(_config(), "POST", "/v1/summarize", {"text": text[:6000], "facts": facts})


def _ollama(text: str, facts: dict) -> str:
    body = {"model": OLLAMA_MODEL, "messages": _messages(text, facts), "format": SCHEMA, "stream": False,
            "think": False, "options": {"temperature": 0.2}}
    return _post(OLLAMA_URL, body, {}, 120)["message"]["content"]


def parse(raw: str) -> dict:
    data = json.loads(raw)
    summary = " ".join(str(data.get("summary", "")).split())
    if not summary:
        raise ValueError("empty summary")
    if len(summary) > MAX:
        summary = summary[: MAX - 1] + "…"
    status = data.get("status") if data.get("status") in STATUSES else "progress"
    return {"summary": redact.redact(summary), "status": status}


def summarize(text: str, facts: dict | None = None) -> dict | None:
    """{"summary", "status", "model"} or None when switched off. Raises on provider errors; the sender retries."""
    which = provider()
    if which == "off" or not (text or "").strip():
        return None
    if which == "hub":  # the hub names the model it used
        raw = _hub(text, facts or {})
        return {**parse(json.dumps(raw)), "model": str(raw.get("model") or "hub")[:80]}
    call, model = {"nebius": (_nebius, NEBIUS_MODEL), "ollama": (_ollama, OLLAMA_MODEL)}[which]
    return {**parse(call(text, facts or {})), "model": f"{which}:{model}"}

"""One OpenAI-compatible chat call for every Agent S job.

Production is NVIDIA Nemotron on Nebius Token Factory (PLAN.md §10.1). Development uses Ollama's /v1 endpoint,
which takes the same request, so nothing else changes when credits land. Pick with AGENT_S_PROVIDER;
the default is nebius when NEBIUS_API_KEY is set, ollama otherwise.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from contextvars import ContextVar

# The three Nemotron tiers on Token Factory. The app's model picker pins one; "auto" keeps per-job routing.
TIERS = {"lightning": "nvidia/Nemotron-3_5-Lightning", "super": "nvidia/nemotron-3-super-120b-a12b",
         "ultra": "nvidia/Nemotron-3-Ultra-550b-a55b"}
PROVIDERS = {
    "nebius": {
        "url": "https://api.tokenfactory.nebius.com/v1/chat/completions",
        "key": "NEBIUS_API_KEY",
        "models": {"progress": TIERS["super"], "qa": TIERS["super"], "agent": TIERS["super"], "digest": TIERS["ultra"]},
        "extra": {"reasoning_effort": "low"},
    },
    "ollama": {
        "url": os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/") + "/v1/chat/completions",
        "key": None,
        "models": {job: os.environ.get("AGENT_S_OLLAMA_MODEL", "qwen3:4b") for job in ("progress", "qa", "agent", "digest")},
        "extra": {"reasoning_effort": "none"},
    },
}
_pinned: ContextVar[str | None] = ContextVar("agent_s_tier", default=None)
# How hard the model thinks (Token Factory's reasoning_effort, checked on all three tiers with tools: 14 Oct).
EFFORTS = ("low", "medium", "high", "max")
_effort: ContextVar[str | None] = ContextVar("agent_s_effort", default=None)
_meter: ContextVar[dict | None] = ContextVar("agent_s_meter", default=None)


@contextmanager
def pinned(tier: str | None):
    """Use one Nemotron tier for every call inside this block. Unknown tiers, "auto" and the Ollama provider keep
    the per-job routing."""
    token = _pinned.set(tier if tier in TIERS else None)
    try:
        yield
    finally:
        _pinned.reset(token)


@contextmanager
def effort(level: str | None):
    """Think this hard on every call inside this block. None, or a level the models don't know, keeps the
    provider's own setting."""
    token = _effort.set(level if level in EFFORTS else None)
    try:
        yield
    finally:
        _effort.reset(token)


def _extra(p: dict) -> dict:
    level = _effort.get()
    return {**p["extra"], "reasoning_effort": level} if level else p["extra"]


@contextmanager
def meter():
    """Count the model usage of every call inside this block: {"calls", "in", "out", "model"}. The hub records it
    per team and person for the usage counter."""
    m = {"calls": 0, "in": 0, "out": 0, "model": ""}
    token = _meter.set(m)
    try:
        yield m
    finally:
        _meter.reset(token)


def _count(model: str, raw: dict) -> dict:
    """A response's token counts, added to the open meter (if any)."""
    u = raw.get("usage") or {}
    used = {"in": int(u.get("prompt_tokens") or 0), "out": int(u.get("completion_tokens") or 0)}
    m = _meter.get()
    if m is not None:
        m.update(calls=m["calls"] + 1, model=f"{provider()}:{model}", **{k: m[k] + used[k] for k in ("in", "out")})
    return used


def provider() -> str:
    return os.environ.get("AGENT_S_PROVIDER") or ("nebius" if os.environ.get("NEBIUS_API_KEY") else "ollama")


def _model(job: str) -> str:
    p = provider()
    return TIERS[_pinned.get()] if p == "nebius" and _pinned.get() else PROVIDERS[p]["models"][job]


def model_for(job: str) -> str:
    return f"{provider()}:{_model(job)}"


RETRYABLE = (TimeoutError, urllib.error.URLError, json.JSONDecodeError, KeyError)


def _call(p: dict, model: str, job: str, messages: list[dict], schema: dict, max_tokens: int, timeout: float) -> dict:
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.1,
            "response_format": {"type": "json_schema", "json_schema": {"name": job, "strict": True, "schema": schema}},
            **_extra(p)}
    headers = {"Content-Type": "application/json"}
    if p["key"]:
        headers["Authorization"] = f"Bearer {os.environ[p['key']]}"
    req = urllib.request.Request(p["url"], json.dumps(body).encode(), headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = json.loads(r.read())
    _count(model, raw)
    return json.loads(raw["choices"][0]["message"]["content"])


MAX_TOKENS = {"agent": 2000}  # a plan with a dozen actions needs room; the other jobs fit in 1200


def chat_tools(messages: list[dict], tools: list[dict], max_tokens: int = 2000, timeout: float = 90) -> dict:
    """One step of an agent's tool loop (the Super Agents app runs the loop on the laptop and calls this through
    POST /v1/llm). OpenAI-style tools in, {content, tool_calls, model, usage} out. Same retry rule as chat_json."""
    p = PROVIDERS[provider()]
    model = _model("agent")
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.2, **_extra(p)}
    if tools:
        body.update(tools=tools, tool_choice="auto")
    headers = {"Content-Type": "application/json"}
    if p["key"]:
        headers["Authorization"] = f"Bearer {os.environ[p['key']]}"
    last: Exception | None = None
    for _ in range(2):
        try:
            req = urllib.request.Request(p["url"], json.dumps(body).encode(), headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = json.loads(r.read())
            msg = raw["choices"][0]["message"]
            return {"content": msg.get("content"), "tool_calls": msg.get("tool_calls") or [], "model": f"{provider()}:{model}",
                    "usage": _count(model, raw)}
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500:
                raise
            last = e
        except RETRYABLE as e:
            last = e
        time.sleep(1)
    raise last


def chat_json(job: str, messages: list[dict], schema: dict, max_tokens: int | None = None, timeout: float = 90) -> dict:
    """One retry on a timeout, 429/5xx or malformed JSON (Token Factory sometimes stalls a request; seen in the
    13 Oct eval). If the job's model still fails and it isn't the progress model, fall back to it (PLAN.md §10.1:
    Ultra -> Super). A 4xx other than 429 is a real error and is raised at once."""
    p = PROVIDERS[provider()]
    models = [_model(job)] * 2
    if _model(job) != p["models"]["progress"]:
        models.append(p["models"]["progress"])
    last: Exception | None = None
    for model in models:
        try:
            return _call(p, model, job, messages, schema, max_tokens or MAX_TOKENS.get(job, 1200), timeout)
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500:
                raise
            last = e
        except RETRYABLE as e:
            last = e
        time.sleep(1)
    raise last

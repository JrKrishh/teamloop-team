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

PROVIDERS = {
    "nebius": {
        "url": "https://api.tokenfactory.nebius.com/v1/chat/completions",
        "key": "NEBIUS_API_KEY",
        "models": {"progress": "nvidia/nemotron-3-super-120b-a12b", "qa": "nvidia/nemotron-3-super-120b-a12b",
                   "digest": "nvidia/Nemotron-3-Ultra-550b-a55b"},
        "extra": {"reasoning_effort": "low"},
    },
    "ollama": {
        "url": os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/") + "/v1/chat/completions",
        "key": None,
        "models": {job: os.environ.get("AGENT_S_OLLAMA_MODEL", "qwen3:4b") for job in ("progress", "qa", "digest")},
        "extra": {"reasoning_effort": "none"},
    },
}


def provider() -> str:
    return os.environ.get("AGENT_S_PROVIDER") or ("nebius" if os.environ.get("NEBIUS_API_KEY") else "ollama")


def model_for(job: str) -> str:
    p = provider()
    return f"{p}:{PROVIDERS[p]['models'][job]}"


RETRYABLE = (TimeoutError, urllib.error.URLError, json.JSONDecodeError, KeyError)


def _call(p: dict, model: str, job: str, messages: list[dict], schema: dict, max_tokens: int, timeout: float) -> dict:
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.1,
            "response_format": {"type": "json_schema", "json_schema": {"name": job, "strict": True, "schema": schema}},
            **p["extra"]}
    headers = {"Content-Type": "application/json"}
    if p["key"]:
        headers["Authorization"] = f"Bearer {os.environ[p['key']]}"
    req = urllib.request.Request(p["url"], json.dumps(body).encode(), headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        content = json.loads(r.read())["choices"][0]["message"]["content"]
    return json.loads(content)


def chat_json(job: str, messages: list[dict], schema: dict, max_tokens: int = 1200, timeout: float = 90) -> dict:
    """One retry on a timeout, 429/5xx or malformed JSON (Token Factory sometimes stalls a request; seen in the
    13 Oct eval). If the job's model still fails and it isn't the progress model, fall back to it (PLAN.md §10.1:
    Ultra -> Super). A 4xx other than 429 is a real error and is raised at once."""
    p = PROVIDERS[provider()]
    models = [p["models"][job]] * 2
    if p["models"][job] != p["models"]["progress"]:
        models.append(p["models"]["progress"])
    last: Exception | None = None
    for model in models:
        try:
            return _call(p, model, job, messages, schema, max_tokens, timeout)
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500:
                raise
            last = e
        except RETRYABLE as e:
            last = e
        time.sleep(1)
    raise last

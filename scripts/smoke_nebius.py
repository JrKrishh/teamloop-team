"""Day-1 Token Factory smoke test (PLAN.md §15, Tue 13). Run once credits are live:

    NEBIUS_API_KEY=... python scripts/smoke_nebius.py      # needs: pip install openai

Checks what nebius-stack.md marked unverified: the model IDs exist, reasoning can be switched off, and
`json_schema` and tool calls work on Nemotron. Prints a table and writes docs/research/smoke-<date>.md.
"""

import json
import os
import time
from pathlib import Path

from openai import OpenAI

MODELS = {
    "lightning": "nvidia/Nemotron-3_5-Lightning",
    "super": "nvidia/nemotron-3-super-120b-a12b",
    "ultra": "nvidia/Nemotron-3-Ultra-550b-a55b",
}
SUMMARY = {"name": "turn_summary", "strict": True, "schema": {
    "type": "object", "additionalProperties": False, "required": ["summary", "status"],
    "properties": {"summary": {"type": "string"}, "status": {"type": "string", "enum": ["progress", "blocked", "done"]}}}}
TOOL = [{"type": "function", "function": {"name": "get_timeline", "description": "Events for a task",
         "parameters": {"type": "object", "properties": {"task": {"type": "string"}}, "required": ["task"]}}}]
TURN = "Fixed add() in calc.py (it subtracted). 1 test failed before, 1 passed after. Next: wire the SSE endpoint."
NO_THINK = {"chat_template_kwargs": {"enable_thinking": False}}

nb = OpenAI(base_url="https://api.tokenfactory.nebius.com/v1/", api_key=os.environ["NEBIUS_API_KEY"])


def check(name, model, **kw):
    t = time.perf_counter()
    try:
        r = nb.chat.completions.create(model=model, max_tokens=300, temperature=0.2, **kw)
        msg = r.choices[0].message
        text = msg.content or ""
        ok = "tool call" if msg.tool_calls else ("valid json" if _json(text) else "NOT json")
        # Token Factory returns reasoning in its own field (reasoning_content); only <think> in the content is a leak.
        leak = "<think>" in text
        details = getattr(r.usage, "completion_tokens_details", None)
        thought = getattr(details, "reasoning_tokens", None) or 0
        return [name, f"{(time.perf_counter() - t):.1f}s", ok, "yes" if leak else "no", str(thought),
                f"{r.usage.prompt_tokens}/{r.usage.completion_tokens}", text[:80].replace("\n", " ")]
    except Exception as e:  # noqa: BLE001 - a failed check is a result
        return [name, f"{(time.perf_counter() - t):.1f}s", "ERROR", "-", "-", "-", str(e)[:80]]


def _json(text):
    try:
        json.loads(text)
        return True
    except ValueError:
        return False


def main():
    ids = {m.id for m in nb.models.list().data}
    rows = [["model id present", "", ", ".join(f"{k}={'yes' if v in ids else 'NO'}" for k, v in MODELS.items()), "", "", "", ""]]
    msgs = [{"role": "system", "content": "Summarize this coding-agent turn for a team lead in one sentence."},
            {"role": "user", "content": TURN}]
    fmt = {"type": "json_schema", "json_schema": SUMMARY}
    rows.append(check("lightning json, reasoning_effort=none", MODELS["lightning"], messages=msgs, response_format=fmt, reasoning_effort="none"))
    rows.append(check("lightning json, enable_thinking=false", MODELS["lightning"], messages=msgs, response_format=fmt, extra_body=NO_THINK))
    rows.append(check("super json", MODELS["super"], messages=msgs, response_format=fmt, reasoning_effort="low"))
    rows.append(check("super tool call", MODELS["super"], tools=TOOL, tool_choice="auto",
                      messages=[{"role": "user", "content": "How far is task T-14? Use the tools."}]))
    rows.append(check("ultra plain", MODELS["ultra"], messages=msgs))
    head = ["check", "time", "result", "reasoning in content", "reasoning tokens", "tokens in/out", "sample"]
    table = "\n".join("| " + " | ".join(r) + " |" for r in [head, ["---"] * len(head), *rows])
    print(table)
    out = Path(__file__).resolve().parents[1] / "docs" / "research" / f"smoke-{time.strftime('%Y%m%d')}.md"
    out.write_text(f"# Token Factory smoke test, {time.strftime('%Y-%m-%d %H:%M')}\n\n{table}\n", encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()

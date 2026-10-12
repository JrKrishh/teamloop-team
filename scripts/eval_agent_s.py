"""Agent S eval (PLAN.md §10.3): run every golden stream through the real model and score it.

    python scripts/eval_agent_s.py                       # provider from env: nebius if NEBIUS_API_KEY, else ollama
    AGENT_S_PROVIDER=ollama python scripts/eval_agent_s.py

Scores: percent inside the expected range; blocked detected when expected; uncited claims (items the model
wrote without valid evidence, which Agent S drops). Writes docs/research/eval-<date>-<provider>.md.
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_s"))
from agent_s import llm, progress  # noqa: E402


def main():
    rows, ok_pct, ok_blk, uncited = [], 0, 0, 0
    files = sorted((ROOT / "agent_s" / "golden").glob("*.json"))
    for f in files:
        g = json.loads(f.read_text(encoding="utf-8"))
        t = time.perf_counter()
        try:
            out = progress.estimate(g["task"], g["events"], g.get("title", ""))
        except Exception as e:  # noqa: BLE001 - a failed run is a result
            rows.append([f.stem, "-", "-", "ERROR", "-", "-", str(e)[:60]])
            continue
        lo, hi = g["expect"]["percent"]
        pct_ok = lo <= out["percent"] <= hi
        blk_ok = (out["status"] == "blocked") == g["expect"]["blocked"]
        ok_pct += pct_ok
        ok_blk += blk_ok
        uncited += out["dropped_uncited"]
        rows.append([f.stem, f"{lo}-{hi}", str(out["percent"]), "yes" if pct_ok else "NO",
                     f"{out['status']} ({'ok' if blk_ok else 'WRONG'})", str(out["dropped_uncited"]),
                     f"{time.perf_counter() - t:.0f}s"])
    head = ["stream", "expected %", "got %", "in range", "status", "uncited", "time"]
    table = "\n".join("| " + " | ".join(r) + " |" for r in [head, ["---"] * len(head), *rows])
    n = len(files)
    score = f"**{ok_pct}/{n}** in range, **{ok_blk}/{n}** status right, **{uncited}** uncited claims dropped"
    model = llm.model_for("progress")
    print(table, "\n\n" + score, "| model:", model)
    out = ROOT / "docs" / "research" / f"eval-{time.strftime('%Y%m%d')}-{llm.provider()}.md"
    out.write_text(f"# Agent S eval, {time.strftime('%Y-%m-%d %H:%M')}, {model}\n\n{table}\n\n{score}\n", encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()

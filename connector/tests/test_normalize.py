"""Field maps checked against real Claude Code payloads (tests/fixtures/hooks/claude_code)."""

from pathlib import PureWindowsPath

from conftest import payloads
from teamloop.normalize import claude_code, command_kind, rel, count_tests

ROOT = PureWindowsPath(r"C:\work\calc-demo")


def run(name):
    return [claude_code(p, ROOT) for p in payloads("claude_code", name)]


def test_session_maps_to_expected_kinds():
    kinds = [e["kind"] for e in run("fix_test_session.jsonl")]
    assert kinds == ["session_start"] + ["tool"] * 6 + ["turn_end", "session_end"]


def test_failing_then_passing_test_run():
    tools = [e["facts"] for e in run("fix_test_session.jsonl") if e["kind"] == "tool"]
    tests = [f["cmd"] for f in tools if f["tool"] == "Bash" and f["cmd"]["kind"] == "test"]
    assert tests[0] == {"kind": "test", "ok": False, "failed": 1}  # "1 failed in 1.03s", masked by `; echo EXIT=$?`
    assert tests[-1]["ok"] is True


def test_edits_are_repo_relative():
    files = [e["facts"].get("file") for e in run("fix_test_session.jsonl") if e["kind"] == "tool"]
    assert [f for f in files if f] == ["calc.py", "NOTES.md"]


def test_failed_command_carries_exit_code():
    failed = [e for e in run("failed_command.jsonl") if e["kind"] == "tool"]
    assert failed[0]["facts"]["ok"] is False and failed[0]["facts"]["exit"] == 3


def test_free_text_only_in_local():
    for e in run("fix_test_session.jsonl"):
        if e["kind"] == "turn_end":
            assert e["local"]["text"].startswith("The test now passes")
        assert "local" not in str(e["facts"])
        assert "stdout" not in str(e["facts"]) and "command" not in str(e["facts"])


def test_command_kinds():
    assert command_kind("cd x && python -m pytest -q") == "test"
    assert command_kind("npm run test -- --watch=false") == "test"
    assert command_kind("git commit -m 'x'") == "git"
    assert command_kind("uv pip install -e .") == "install"
    assert command_kind("npm run build") == "build"
    assert command_kind("ls -la") == "other"


def test_counts_take_the_last_summary():
    assert count_tests("1 failed, 2 passed in 0.3s\nretry\n3 passed in 0.2s") == {"passed": 3}
    assert count_tests("Tests: 1 failed, 4 passed, 5 total") == {"failed": 1, "passed": 4}
    assert count_tests("no summary here") == {}


def test_rel_never_returns_machine_paths():
    assert rel(r"C:\work\calc-demo\src\a.py", ROOT) == "src/a.py"
    assert rel("C:/work/calc-demo/src/a.py", ROOT) == "src/a.py"
    assert rel(r"C:\Users\dev\secret\b.py", ROOT) == "b.py"
    assert rel("/home/dev/proj/c.py", None) == "c.py"


# --- Codex (real payloads, tests/fixtures/hooks/codex) ---
from teamloop.normalize import codex  # noqa: E402


def run_codex(name):
    return [codex(p, ROOT) for p in payloads("codex", name)]


def test_codex_session_kinds():
    kinds = [e["kind"] for e in run_codex("fix_test_session.jsonl")]
    assert kinds == ["session_start"] + ["tool"] * 5 + ["turn_end", "session_end"]


def test_codex_tests_judged_from_output_not_exit_code():
    cmds = [e["facts"]["cmd"] for e in run_codex("fix_test_session.jsonl") if e["facts"].get("tool") == "Bash"]
    assert cmds[0] == {"kind": "test", "ok": False, "failed": 1}
    assert {"kind": "test", "ok": True, "passed": 1} in cmds
    assert cmds[-1] == {"kind": "other", "ok": None}  # sys.exit(3): Codex reports no exit status at all


def test_codex_apply_patch_files_and_exit():
    [patch] = [e["facts"] for e in run_codex("fix_test_session.jsonl") if e["facts"].get("tool") == "apply_patch"]
    assert patch == {"tool": "apply_patch", "ok": True, "file": "calc.py"}


def test_codex_turn_text_stays_local():
    [turn] = [e for e in run_codex("fix_test_session.jsonl") if e["kind"] == "turn_end"]
    assert turn["local"]["text"].startswith("Fixed `calc.py`") and turn["facts"] == {}

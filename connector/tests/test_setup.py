"""init / doctor / Claude Code settings merge, in throwaway repos. The real `claude` CLI is never called."""

import json
import subprocess

import pytest

from teamloop import claude, doctor, githook, init


@pytest.fixture
def project(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(claude, "register_mcp", lambda cwd, scope: "registered (test)")
    monkeypatch.setattr(claude, "mcp_registered", lambda cwd: True)
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "T-8-init"], cwd=root, check=True)
    monkeypatch.chdir(root)
    return root


def test_merge_is_idempotent_and_keeps_other_hooks():
    other = {"type": "command", "command": "entire hook"}
    settings = {"hooks": {"Stop": [{"hooks": [other]}]}, "model": "opus"}
    assert len(claude.merge(settings, "py -m teamloop hook claude_code")) == len(claude.EVENTS)
    assert claude.merge(settings, "py -m teamloop hook claude_code") == []
    assert other in settings["hooks"]["Stop"][0]["hooks"] and settings["model"] == "opus"
    assert claude.missing(settings) == []
    assert claude.merge(settings, '"/new/python" -m teamloop hook claude_code') == [f"updated {e}" for e in claude.EVENTS]
    assert settings["hooks"]["PostToolUse"][0]["matcher"] == "*"


def test_init_writes_local_settings_kept_out_of_git(project):
    assert init.run("local") == 0
    settings = json.loads((project / ".claude" / "settings.local.json").read_text())
    assert claude.missing(settings) == []
    assert ".claude" not in subprocess.run(["git", "status", "--porcelain"], cwd=project, capture_output=True, text=True).stdout
    assert githook.MARK in (githook.hooks_dir(project) / githook.NAME).read_text()
    assert init.run("local") == 0  # second run changes nothing
    assert json.loads((project / ".claude" / "settings.local.json").read_text()) == settings


def test_init_refuses_to_clobber_broken_json(project):
    path = project / ".claude" / "settings.local.json"
    path.parent.mkdir()
    path.write_text("{ broken")
    assert init.run("local") == 1 and path.read_text() == "{ broken"


def test_init_dry_run_writes_nothing(project):
    assert init.run("local", dry_run=True) == 0
    assert not (project / ".claude").exists()


def test_init_outside_a_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert init.run("local") == 2


def test_doctor_after_init_has_no_failures(project):
    before = {lvl for lvl, _, _ in doctor.checks(project)}
    assert "fail" in before
    init.run("local")
    rows = doctor.checks(project)
    assert [r for r in rows if r[0] == "fail"] == []
    assert any("task T-8" in m for _, m, _ in rows)


def test_doctor_names_the_fix(project):
    rows = doctor.checks(project)
    fixes = {fix for lvl, _, fix in rows if lvl == "fail"}
    assert "teamloop init" in fixes and "teamloop git-hook install" in fixes

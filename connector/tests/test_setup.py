"""init / doctor / Claude Code settings merge, in throwaway repos. The real `claude` CLI is never called."""

import json
import subprocess

import pytest

from teamloop import claude, codex, doctor, githook, init


@pytest.fixture
def project(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(claude, "register_mcp", lambda cwd, scope: "registered (test)")
    monkeypatch.setattr(claude, "mcp_registered", lambda cwd: True)
    monkeypatch.setattr(codex, "cli", lambda: None)  # never touch the real ~/.codex in tests
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


def test_init_wires_codex_when_installed(project, monkeypatch):
    calls = []
    monkeypatch.setattr(codex, "cli", lambda: "codex")
    monkeypatch.setattr(codex, "register_mcp", lambda: calls.append("mcp") or "registered (test)")
    monkeypatch.setattr(codex, "mcp_registered", lambda: bool(calls))
    assert init.run("local") == 0 and calls == ["mcp"]
    hooks = json.loads((project / ".codex" / "hooks.json").read_text())
    assert claude.missing(hooks, codex.EVENTS, codex.TAG) == []
    cmd = hooks["hooks"]["Stop"][0]["hooks"][0]["command"]
    assert not cmd.startswith('"')  # Codex runs hooks through PowerShell on Windows: a leading quote fails silently
    assert ".codex" not in subprocess.run(["git", "status", "--porcelain"], cwd=project, capture_output=True, text=True).stdout
    assert [r for r in doctor.checks(project) if r[0] == "fail"] == []


def test_no_command_on_a_new_laptop_starts_sign_in(monkeypatch, capsys):
    from teamloop import cli, launch, login

    hubs = []
    monkeypatch.setattr(launch, "_hub_running", lambda: False)
    monkeypatch.setattr(login, "device_login", lambda hub: hubs.append(hub) or 1)
    monkeypatch.setattr("builtins.input", lambda *a: "")
    assert cli.main([]) == 0
    assert hubs == ["https://teamloop.vercel.app"] and "sign in" in capsys.readouterr().out


def test_no_command_opens_a_running_hub(monkeypatch):
    from teamloop import cli, launch

    opened = []
    monkeypatch.setattr(launch, "_hub_running", lambda: True)
    monkeypatch.setattr(launch.window, "open_app", opened.append)
    assert cli.main([]) == 0 and opened == ["http://localhost:8799"]


def test_no_command_opens_the_cloud_board_when_signed_in(monkeypatch, teamloop_home):
    from teamloop import cli, launch

    opened = []
    teamloop_home.mkdir(parents=True, exist_ok=True)
    (teamloop_home / "config.json").write_text(json.dumps({"mode": "cloud", "url": "https://example.test", "token": "tl_x"}))
    monkeypatch.setattr(launch, "_hub_running", lambda: True)  # even with a self-hosted hub around
    monkeypatch.setattr(launch.window, "open_app", opened.append)
    assert cli.main([]) == 0 and opened == ["https://example.test"]

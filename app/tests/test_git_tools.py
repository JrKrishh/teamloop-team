"""Agents commit, push and open pull requests like Claude Code: with real git against a local remote. Commits take
named files only and never land on the default branch; pushes never force; no gh here, so a pull request opens as
GitHub's own page."""

import shutil
import subprocess

import pytest

from superagents import laptop
from superagents.runtime import tools


def git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    # nothing from this laptop's own git config (signing, hooks, helpers) reaches the tests
    (tmp_path / "gitconfig").write_text("[user]\n\tname = Test\n\temail = test@example.com\n[init]\n\tdefaultBranch = main\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    git(tmp_path, "init", "--bare", "-b", "main", "remote.git")
    git(tmp_path, "clone", "remote.git", "seed")
    (tmp_path / "seed" / "README.md").write_text("# web\n")
    git(tmp_path / "seed", "add", "README.md")
    git(tmp_path / "seed", "commit", "-m", "First")
    git(tmp_path / "seed", "push", "origin", "main")
    git(tmp_path, "clone", "remote.git", "web")
    work = tmp_path / "web"
    monkeypatch.setattr(tools, "roots", lambda: {"web": work})
    return work


def test_commits_only_the_named_files_on_a_branch_never_the_default(repo):
    (repo / "a.txt").write_text("a\n")
    (repo / "b.txt").write_text("b\n")
    git(repo, "add", "b.txt")  # staged by the person, not named by the agent
    st = tools.git_status(None)
    assert "default branch main" in st and "## main...origin/main" in st and "a.txt" in st
    with pytest.raises(ValueError, match="default branch"):
        tools.git_commit(None, "Add a", ["a.txt"])
    assert "a new branch feat/a" in tools.git_branch(None, "feat/a")
    out = tools.git_commit(None, "Add a\n\nWhy: the demo needs it.", ["web/a.txt"])  # the other tools' path form works
    assert "on feat/a" in out
    assert git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["a.txt"]
    assert git(repo, "log", "-1", "--format=%B").strip() == "Add a\n\nWhy: the demo needs it."
    assert "A  b.txt" in tools.git_status(None)  # still staged, still the person's
    assert "the existing branch main" in tools.git_branch(None, "main")


def test_the_commit_hook_tags_the_agents_commits_and_not_the_persons(repo, monkeypatch):
    import sys

    from teamloop import githook

    for k in ("CLAUDECODE", "CURSOR_AGENT", "TEAMLOOP_AGENT"):  # these tests may run inside an agent's own shell
        monkeypatch.delenv(k, raising=False)
    githook.install(repo)
    tools.git_branch(None, "T-7-totals")
    (repo / "a.txt").write_text("a\n")
    tools.git_commit(None, "Add totals", ["a.txt"])
    assert git(repo, "log", "-1", "--format=%B").strip() == "Add totals\n\nTeamLoop-Task: T-7"
    (repo / "b.txt").write_text("b\n")
    git(repo, "add", "b.txt")
    git(repo, "commit", "-m", "By hand")
    assert git(repo, "log", "-1", "--format=%B").strip() == "By hand"
    said = tools.run_command(None, "Write-Output $env:TEAMLOOP_AGENT" if sys.platform == "win32" else "echo $TEAMLOOP_AGENT")
    assert said.rstrip().endswith("superagents")  # the agent's own commands carry the mark too


def test_the_app_brings_an_older_commit_hook_up_to_date(repo, monkeypatch):
    from teamloop import githook

    hooks = githook.hooks_dir(repo)
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / githook.NAME).write_text(f"#!/bin/sh\n{githook.MARK}: adds a TeamLoop-Task trailer.\nexit 0\n", newline="\n")
    monkeypatch.setattr(laptop.store, "repos", lambda: [str(repo)])
    assert laptop.update_commit_hooks() == 1 and githook.current(repo) is True
    assert laptop.update_commit_hooks() == 0  # once


def test_refuses_files_outside_the_repo_and_bad_branch_names(repo):
    tools.git_branch(None, "feat/x")
    for bad in (["../evil.txt"], ["."], [str(repo.parent / "seed" / "README.md")]):
        with pytest.raises(PermissionError):
            tools.git_commit(None, "x", bad)
    with pytest.raises(ValueError, match="Name the files"):
        tools.git_commit(None, "x", [])
    for bad in ("-x", "a..b", "a b", "", "x.lock"):
        with pytest.raises(ValueError):
            tools.git_branch(None, bad)


def test_pushes_a_branch_then_opens_githubs_pull_request_page(repo, monkeypatch):
    with pytest.raises(ValueError, match="default branch"):
        tools.git_push(None)
    tools.git_branch(None, "feat/c")
    (repo / "c.txt").write_text("c\n")
    tools.git_commit(None, "Add c", ["c.txt"])
    with pytest.raises(ValueError, match="origin isn't on GitHub"):
        tools.open_pr(None, "Add c")
    assert "Pushed feat/c" in tools.git_push(None)
    assert "refs/heads/feat/c" in git(repo.parent / "remote.git", "for-each-ref", "--format=%(refname)")
    git(repo, "remote", "set-url", "origin", "git@github.com:acme/web.git")
    real_which, opened = shutil.which, []
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: None if name == "gh" else real_which(name, *a, **k))
    monkeypatch.setattr("webbrowser.open", opened.append)
    out = tools.open_pr(None, "Add c", "Adds c.\n\nCloses T-12")
    assert opened[0].startswith("https://github.com/acme/web/compare/main...feat/c?quick_pull=1&title=Add+c&body=Adds+c.")
    assert "clicks Create" in out


def test_pulls_fast_forward_only(repo):
    other = repo.parent / "seed"
    (other / "d.txt").write_text("d\n")
    git(other, "add", "d.txt")
    git(other, "commit", "-m", "Add d")
    git(other, "push", "origin", "main")
    tools.git_pull(None)
    assert (repo / "d.txt").exists()
    (other / "e.txt").write_text("e\n")
    git(other, "add", "e.txt")
    git(other, "commit", "-m", "Add e")
    git(other, "push", "origin", "main")
    (repo / "f.txt").write_text("f\n")
    git(repo, "add", "f.txt")
    git(repo, "commit", "-m", "Local f")  # both sides moved
    with pytest.raises(RuntimeError, match="fast-forward"):
        tools.git_pull(None)


def test_github_urls_and_get_the_project(repo, tmp_path, monkeypatch):
    assert tools.github_repo("git@github.com:acme/web.git") == tools.github_repo("https://github.com/acme/web") == "acme/web"
    assert tools.github_repo("https://gitlab.com/acme/web") is None
    monkeypatch.setattr(laptop, "connect_repo", lambda path: {"ok": True, "repo": {"path": path}})
    (tmp_path / "projects").mkdir()
    got = laptop.clone(str(tmp_path / "remote.git"), str(tmp_path / "projects"))
    assert got["ok"] and (tmp_path / "projects" / "remote" / "README.md").exists()
    with pytest.raises(FileExistsError):
        laptop.clone(str(tmp_path / "remote.git"), str(tmp_path / "projects"))

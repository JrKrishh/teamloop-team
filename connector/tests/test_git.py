"""Commit trailer hook and repo facts, in throwaway git repos."""

import os
import subprocess

from teamloop import githook, repo

MARKS = {"claude": ("CLAUDECODE", "1"), "cursor": ("CURSOR_AGENT", "1"), "app": ("TEAMLOOP_AGENT", "superagents")}


def sh(*args, cwd, agent=None):
    """agent: whose commands these are (None: a person's). The tests may themselves run inside an agent's shell."""
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CURSOR_AGENT", "TEAMLOOP_AGENT")}
    if agent:
        env[MARKS[agent][0]] = MARKS[agent][1]
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True, env=env).stdout.strip()


def new_repo(path, branch="main"):
    path.mkdir()
    sh("git", "init", "-q", "-b", branch, cwd=path)
    sh("git", "config", "user.email", "t@example.com", cwd=path)
    sh("git", "config", "user.name", "T", cwd=path)
    return path


def commit(path, msg="work", *extra, agent="claude"):
    (path / "f.txt").write_text(msg)
    sh("git", "add", "-A", cwd=path)
    sh("git", "commit", "-q", "-m", msg, *extra, cwd=path, agent=agent)
    return sh("git", "log", "-1", "--format=%B", cwd=path)


def test_trailer_from_config_even_with_no_verify(tmp_path):
    r = new_repo(tmp_path / "r")
    githook.install(r)
    sh("git", "config", "teamloop.task", "T-14", cwd=r)
    assert commit(r, "add sse", "--no-verify").endswith("TeamLoop-Task: T-14")


def test_trailer_from_branch_name(tmp_path):
    r = new_repo(tmp_path / "r", branch="T-9-github-app")
    githook.install(r)
    assert "TeamLoop-Task: T-9" in commit(r)


def test_no_task_no_trailer(tmp_path):
    r = new_repo(tmp_path / "r")
    githook.install(r)
    assert commit(r) == "work"


def test_commits_made_by_hand_are_left_alone(tmp_path):
    """Super Team follows agents' work: a person's own commit gets no trailer, on a task's branch or not. Nothing names
    the agent either (no attribution line)."""
    r = new_repo(tmp_path / "r", branch="T-9-github-app")
    githook.install(r)
    assert commit(r, "by hand", agent=None) == "by hand"
    assert commit(r, "the editor's agent", agent="cursor") == "the editor's agent\n\nTeamLoop-Task: T-9"
    assert commit(r, "the app's agent", agent="app") == "the app's agent\n\nTeamLoop-Task: T-9"


def test_codex_is_found_among_the_processes_that_started_the_commit():
    table = {10: (5, "sh.exe"), 5: (4, "git.exe"), 4: (3, "powershell.exe"), 3: (2, "codex-command-runner.exe"), 2: (1, "codex.exe")}
    assert githook.agent_of(10, table) == "codex"
    assert githook.agent_of(4, {4: (3, "powershell.exe"), 3: (2, "explorer.exe")}) is None
    assert githook.agent_of(1, {1: (2, "a.exe"), 2: (1, "b.exe")}) is None  # a loop in stale parent ids ends
    me = githook.processes()[os.getpid()]
    assert "python" in me[1] and githook.agent_of() is None  # these tests run under no Codex


def test_amend_does_not_duplicate(tmp_path):
    r = new_repo(tmp_path / "r")
    githook.install(r)
    sh("git", "config", "teamloop.task", "T-1", cwd=r)
    commit(r)
    sh("git", "commit", "-q", "--amend", "--no-edit", cwd=r, agent="claude")
    assert sh("git", "log", "-1", "--format=%B", cwd=r).count("TeamLoop-Task") == 1


def test_existing_hook_is_kept_and_still_runs(tmp_path):
    r = new_repo(tmp_path / "r")
    hooks = githook.hooks_dir(r)
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "prepare-commit-msg").write_text('#!/bin/sh\necho "Entire-Checkpoint: abc123" >> "$1"\n', newline="\n")
    (hooks / "prepare-commit-msg").chmod(0o755)
    assert "kept" in githook.install(r)
    assert "already installed" in githook.install(r)
    sh("git", "config", "teamloop.task", "T-3", cwd=r)
    msg = commit(r)
    assert "Entire-Checkpoint: abc123" in msg and "TeamLoop-Task: T-3" in msg


def test_an_older_hook_is_flagged_and_brought_up_to_date(tmp_path):
    r = new_repo(tmp_path / "r")
    hooks = githook.hooks_dir(r)
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / githook.NAME).write_text(f"#!/bin/sh\n{githook.MARK}: adds a TeamLoop-Task trailer.\nexit 0\n", newline="\n")
    assert githook.current(r) is False  # the one that tagged hand-made commits too
    githook.install(r)
    assert githook.current(r) is True and githook.current(new_repo(tmp_path / "s")) is None


def test_repo_facts_without_spawning_git(tmp_path):
    r = new_repo(tmp_path / "r", branch="feat/T-21-board")
    (r / "src").mkdir()
    found = repo.find(r / "src")
    assert found.root == r and repo.branch(found) == "feat/T-21-board"
    assert repo.task(found) == "T-21"
    sh("git", "config", "teamloop.task", "T-30", cwd=r)
    assert repo.task(found) == "T-30"  # config beats the branch name


def test_worktree_reads_shared_config(tmp_path):
    r = new_repo(tmp_path / "r")
    commit(r)
    sh("git", "config", "teamloop.task", "T-5", cwd=r)
    sh("git", "worktree", "add", "-q", "-b", "side", str(tmp_path / "wt"), cwd=r)
    found = repo.find(tmp_path / "wt")
    assert found.root == tmp_path / "wt" and repo.branch(found) == "side" and repo.task(found) == "T-5"

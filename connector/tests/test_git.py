"""Commit trailer hook and repo facts, in throwaway git repos."""

import subprocess

from teamloop import githook, repo


def sh(*args, cwd):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def new_repo(path, branch="main"):
    path.mkdir()
    sh("git", "init", "-q", "-b", branch, cwd=path)
    sh("git", "config", "user.email", "t@example.com", cwd=path)
    sh("git", "config", "user.name", "T", cwd=path)
    return path


def commit(path, msg="work", *extra):
    (path / "f.txt").write_text(msg)
    sh("git", "add", "-A", cwd=path)
    sh("git", "commit", "-q", "-m", msg, *extra, cwd=path)
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
    assert "TeamLoop-Task" not in commit(r)


def test_amend_does_not_duplicate(tmp_path):
    r = new_repo(tmp_path / "r")
    githook.install(r)
    sh("git", "config", "teamloop.task", "T-1", cwd=r)
    commit(r)
    sh("git", "commit", "-q", "--amend", "--no-edit", cwd=r)
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

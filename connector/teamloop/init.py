"""`teamloop init`: connect this repo's coding tools in one command (PLAN.md §9.1, US-1).

Default scope is `local`: hooks go in <repo>/.claude/settings.local.json, which is personal and kept out of git,
so teammates who haven't installed TeamLoop are never affected. `--scope user` covers every repo.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from teamloop import claude, githook, repo


def _keep_out_of_git(found: repo.Repo, rel_path: str) -> None:
    ignored = subprocess.run(["git", "check-ignore", "-q", rel_path], cwd=found.root).returncode == 0
    if ignored:
        return
    exclude = found.common_dir / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    with open(exclude, "a", encoding="utf-8") as f:
        f.write(f"\n{rel_path}\n")


def run(scope: str = "local", dry_run: bool = False) -> int:
    found = repo.find(Path.cwd())
    if scope == "local" and found is None:
        print("Not in a git repo. cd into your project, or use `teamloop init --scope user` for every repo.")
        return 2
    root = found.root if found else Path.cwd()

    path = claude.settings_path(scope, found.root if found else None)
    try:
        settings = claude.load(path)
    except json.JSONDecodeError as e:
        print(f"{path} is not valid JSON ({e}); fix it first, nothing was changed.")
        return 1
    changes = claude.merge(settings, claude.hook_command())
    print(f"Claude Code hooks -> {path}")
    print("  " + (", ".join(changes) if changes else "already set"))
    if dry_run:
        print("Dry run: nothing written.")
        return 0
    if changes:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        if scope == "local":
            _keep_out_of_git(found, ".claude/settings.local.json")

    print("MCP -> " + claude.register_mcp(root, "local" if scope == "local" else "user"))
    if found:
        print("Commit hook -> " + githook.install(found.root))
    print('\nNext: `teamloop task T-<id> "title"`, restart your Claude Code session, then `teamloop doctor`.')
    return 0

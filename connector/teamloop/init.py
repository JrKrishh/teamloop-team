"""`teamloop init`: connect this repo's coding tools in one command (PLAN.md §9.1, US-1).

Default scope is `local`: hooks go in <repo>/.claude/settings.local.json, which is personal and kept out of git,
so teammates who haven't installed TeamLoop are never affected. `--scope user` covers every repo.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from teamloop import claude, codex, githook, repo


def _keep_out_of_git(found: repo.Repo, rel_path: str) -> None:
    ignored = subprocess.run(["git", "check-ignore", "-q", rel_path], cwd=found.root).returncode == 0
    if ignored:
        return
    exclude = found.common_dir / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    with open(exclude, "a", encoding="utf-8") as f:
        f.write(f"\n{rel_path}\n")


def _wire(label: str, path: Path, command: str, events: dict, tag: str, dry_run: bool) -> list[str] | None:
    try:
        settings = claude.load(path)
    except json.JSONDecodeError as e:
        print(f"{path} is not valid JSON ({e}); fix it first, then run init again.")
        return None
    changes = claude.merge(settings, command, events, tag)
    print(f"{label} hooks -> {path}")
    print("  " + (", ".join(changes) if changes else "already set"))
    if changes and not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return changes


def run(scope: str = "local", dry_run: bool = False, where: Path | None = None) -> int:
    """`where` is the folder to connect (the desktop app passes the one you picked); the CLI uses the current one."""
    where = where or Path.cwd()
    found = repo.find(where)
    if scope == "local" and found is None:
        print("Not in a git repo. cd into your project, or use `teamloop init --scope user` for every repo.")
        return 2
    root = found.root if found else where
    repo_root = found.root if found else None

    targets = [("Claude Code", claude.settings_path(scope, repo_root), claude.hook_command(), claude.EVENTS, claude.TAG,
                ".claude/settings.local.json")]
    has_codex = codex.cli() is not None
    if has_codex:
        targets.append(("Codex", codex.hooks_path(scope, repo_root), codex.hook_command(), codex.EVENTS, codex.TAG,
                        ".codex/hooks.json"))
    for label, path, command, events, tag, rel_path in targets:
        changes = _wire(label, path, command, events, tag, dry_run)
        if changes is None:
            return 1
        if changes and scope == "local" and not dry_run:
            _keep_out_of_git(found, rel_path)
    if dry_run:
        print("Dry run: nothing written.")
        return 0

    print("Claude Code MCP -> " + claude.register_mcp(root, "local" if scope == "local" else "user"))
    if has_codex:
        print("Codex MCP -> " + codex.register_mcp())
        print("  Codex asks you to trust repo hooks once: run `codex`, type /hooks, approve the TeamLoop ones.")
    if found:
        print("Commit hook -> " + githook.install(found.root))
    print('\nNext: `teamloop task T-<id> "title"`, restart your coding sessions, then `teamloop doctor`.')
    return 0

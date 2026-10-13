"""Skills, in Claude Code's format: a folder with SKILL.md (frontmatter `name` and `description`, then the
instructions) and any files it refers to. Bundled skills ship with the app; yours live in ~/.teamloop/skills.

An agent sees every enabled skill's name and description; "always on" skills (Karpathy's guidelines by default) are
in its instructions in full, the others it reads with the load_skill tool when they fit the task."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from teamloop import spool

BUNDLED = Path(__file__).parents[1] / "skills"
DEFAULT_ON = ("karpathy-guidelines",)
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
MAX_SKILL_BYTES = 200_000


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    bundled: bool

    def body(self) -> str:
        return _split(self.path.joinpath("SKILL.md").read_text(encoding="utf-8"))[1]

    def files(self) -> list[str]:
        return sorted(p.relative_to(self.path).as_posix() for p in self.path.rglob("*") if p.is_file() and p.name != "SKILL.md")

    def read(self, rel: str) -> str:
        target = (self.path / rel).resolve()
        if self.path.resolve() not in target.parents or not target.is_file():
            raise FileNotFoundError(rel)
        return target.read_text(encoding="utf-8", errors="replace")[:MAX_SKILL_BYTES]


def user_dir() -> Path:
    return spool.home() / "skills"


def _split(text: str) -> tuple[dict, str]:
    meta: dict = {}
    if text.startswith("---"):
        head, _, rest = text[3:].partition("\n---")
        for line in head.splitlines():
            key, sep, value = line.partition(":")
            if sep and key.strip() and not line.startswith(" "):
                meta[key.strip()] = value.strip().strip('"').strip("'")
        return meta, rest.lstrip("\n")
    return meta, text


def _load(folder: Path, bundled: bool) -> Skill | None:
    f = folder / "SKILL.md"
    if not f.is_file() or f.stat().st_size > MAX_SKILL_BYTES:
        return None
    meta, _ = _split(f.read_text(encoding="utf-8", errors="replace"))
    name = meta.get("name") or folder.name
    if not NAME.match(name):
        return None
    return Skill(name, " ".join((meta.get("description") or "").split())[:400], folder, bundled)


def all_skills() -> dict[str, Skill]:
    """Bundled first; a skill of yours with the same name replaces the bundled one."""
    found: dict[str, Skill] = {}
    for root, bundled in ((BUNDLED, True), (user_dir(), False)):
        if root.is_dir():
            for folder in sorted(p for p in root.iterdir() if p.is_dir()):
                s = _load(folder, bundled)
                if s:
                    found[s.name] = s
    return found


def save(name: str, description: str, body: str) -> Skill:
    if not NAME.match(name):
        raise ValueError("Skill names use lowercase letters, digits and dashes")
    folder = user_dir() / name
    if not folder.exists() and (BUNDLED / name).is_dir():  # your copy of a built-in skill keeps its other files
        shutil.copytree(BUNDLED / name, folder)
    folder.mkdir(parents=True, exist_ok=True)
    desc = " ".join(description.split())
    folder.joinpath("SKILL.md").write_text(f"---\nname: {name}\ndescription: {desc}\n---\n\n{body.strip()}\n", encoding="utf-8")
    return _load(folder, False)


def delete(name: str) -> None:
    folder = user_dir() / name
    if not NAME.match(name) or not folder.is_dir():
        raise FileNotFoundError(name)
    shutil.rmtree(folder)


def claude_code_skills() -> list[Skill]:
    """Skills installed for Claude Code (~/.claude/skills), offered for import. Read only."""
    root = Path.home() / ".claude" / "skills"
    return [s for s in (_load(p, False) for p in sorted(root.iterdir()) if p.is_dir()) if s] if root.is_dir() else []


def import_claude_code(name: str) -> Skill:
    src = next((s for s in claude_code_skills() if s.name == name), None)
    if not src:
        raise FileNotFoundError(name)
    dst = user_dir() / name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src.path, dst, ignore=shutil.ignore_patterns(".git", "node_modules", "__pycache__"))
    return _load(dst, False)

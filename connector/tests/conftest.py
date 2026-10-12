import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "hooks"


def payloads(tool: str, name: str) -> list[dict]:
    return [json.loads(line) for line in (FIXTURES / tool / name).read_text(encoding="utf-8").splitlines() if line]


@pytest.fixture(autouse=True)
def teamloop_home(tmp_path, monkeypatch):
    home = tmp_path / "tl-home"
    monkeypatch.setenv("TEAMLOOP_HOME", str(home))
    monkeypatch.delenv("TEAMLOOP_TASK", raising=False)
    return home

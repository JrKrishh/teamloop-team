"""One version for the whole product: the app, the connector inside it, both hubs, Agent S and the phone app.
They ship together, so a release bumps them together (docs/release.md); /healthz then tells deploys apart."""

import re
from pathlib import Path

from superagents import __version__

ROOT = Path(__file__).resolve().parents[2]


def test_every_part_has_the_apps_version():
    found = {f"{pkg}/pyproject.toml": re.search(r'^version = "([^"]+)"', (ROOT / pkg / "pyproject.toml").read_text(), re.M)[1]
             for pkg in ("agent_s", "app", "cloud", "connector", "hub")}
    for init in ("cloud/cloud", "connector/teamloop", "hub/hub"):
        found[f"{init}/__init__.py"] = re.search(r'__version__ = "([^"]+)"', (ROOT / init / "__init__.py").read_text())[1]
    found["android versionName"] = re.search(r'versionName = "([^"]+)"', (ROOT / "android/app/build.gradle.kts").read_text())[1]
    assert {k: v for k, v in found.items() if v != __version__} == {}

"""Hide secrets before anything is written, even to the local spool.

Adapted from TeamLoop neatHack's `keys/redact.py` (MIT): secrets are hidden by value (any env var whose
name looks like a key) and by shape (well-known key formats).
"""

from __future__ import annotations

import os
import re
from typing import Any

HIDDEN = "[hidden]"
_SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIALS?)(_\d+)?$", re.I)
_SHAPES = [re.compile(p) for p in (
    r"sk-ant-[A-Za-z0-9_\-]{20,}",                      # Anthropic
    r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}",                # OpenAI and lookalikes
    r"gh[pousr]_[A-Za-z0-9]{30,}",                      # GitHub tokens
    r"github_pat_[A-Za-z0-9_]{40,}",
    r"AKIA[0-9A-Z]{16}",                                # AWS access key id
    r"AIza[0-9A-Za-z_\-]{35}",                          # Google API key
    r"xox[abpr]-[A-Za-z0-9\-]{10,}",                    # Slack
    r"gsk_[A-Za-z0-9]{40,}",                            # Groq
    r"tvly-[A-Za-z0-9\-]{20,}",                         # Tavily
    r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}",  # JWT
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
    r"(?i)(?<=bearer )[A-Za-z0-9._\-]{16,}",
)]
# NAME=value / NAME: value where NAME looks secret: keep the name, hide the value.
_ASSIGN = re.compile(r"(?i)\b([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD)[A-Z0-9_]*)(\s*[=:]\s*)(['\"]?)[^\s'\"]{6,}\3")


def _env_secrets() -> list[str]:
    vals = {v for k, v in os.environ.items() if _SECRET_NAME.search(k) and len(v or "") >= 12}
    return sorted(vals, key=len, reverse=True)


def redact(text: str) -> str:
    if not text:
        return text
    for secret in _env_secrets():
        text = text.replace(secret, HIDDEN)
    for shape in _SHAPES:
        text = shape.sub(HIDDEN, text)
    return _ASSIGN.sub(lambda m: f"{m.group(1)}{m.group(2)}{HIDDEN}", text)


def redact_obj(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_obj(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_obj(v) for v in value]
    return value

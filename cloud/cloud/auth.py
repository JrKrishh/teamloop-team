"""Who is asking. Three kinds of caller:

- a person in a browser or the app window: signed in with Supabase (GitHub or email/password) once, then a hub
  session cookie (HttpOnly) carries them;
- a connector (`teamloop` CLI, hooks, MCP server): a `tl_` token from the device flow, bound to one person in
  one team;
- nobody: may read the public demo only.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

SESSION_COOKIE = "teamloop_session"
SESSION_DAYS = 30


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(32)


@dataclass(frozen=True)
class Person:
    id: str
    email: Optional[str]
    name: str


def supabase_user(access_token: str) -> Person:
    """Ask Supabase Auth who this access token belongs to. Raises PermissionError when it doesn't check out."""
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/auth/v1/user"
    req = urllib.request.Request(url, headers={"apikey": os.environ["SUPABASE_PUBLISHABLE_KEY"],
                                               "Authorization": f"Bearer {access_token}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            u = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise PermissionError(f"Supabase refused the sign-in ({e.code})") from None
    meta = u.get("user_metadata") or {}
    email = u.get("email")
    # GitHub accounts may have no display name: then the GitHub username, then the email's local part
    name = (meta.get("full_name") or meta.get("name") or meta.get("user_name") or meta.get("preferred_username")
            or (email or "").split("@")[0] or "someone").strip()[:64]
    return Person(id=u["id"], email=email, name=name)

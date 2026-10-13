"""Sign-in with Supabase Auth, done by the app itself (no supabase-js): GitHub through the system browser with PKCE and
a loopback redirect (RFC 8252, like `gh auth login`), or email and password. Either way the result is a Supabase
access token, which the hub trades for its own session (POST /v1/app/session)."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request


class AuthError(Exception):
    pass


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def authorize_url(supabase_url: str, redirect_to: str, challenge: str, provider: str = "github") -> str:
    q = urllib.parse.urlencode({"provider": provider, "redirect_to": redirect_to, "code_challenge": challenge,
                                "code_challenge_method": "s256"})
    return f"{supabase_url.rstrip('/')}/auth/v1/authorize?{q}"


def _post(supabase_url: str, key: str, path: str, body: dict) -> dict:
    req = urllib.request.Request(f"{supabase_url.rstrip('/')}/auth/v1/{path}", json.dumps(body).encode(),
                                 {"apikey": key, "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read())
        except ValueError:
            detail = {}
        raise AuthError(detail.get("msg") or detail.get("error_description") or detail.get("message")
                        or f"Supabase said {e.code}") from None
    except OSError as e:
        raise AuthError(f"Couldn't reach the sign-in service: {e}") from None


def exchange_code(supabase_url: str, key: str, code: str, verifier: str) -> dict:
    """The `code` GitHub sign-in sent back to the loopback page -> a session {access_token, user, ...}."""
    return _post(supabase_url, key, "token?grant_type=pkce", {"auth_code": code, "code_verifier": verifier})


def password(supabase_url: str, key: str, email: str, pw: str) -> dict:
    return _post(supabase_url, key, "token?grant_type=password", {"email": email, "password": pw})


def signup(supabase_url: str, key: str, email: str, pw: str, name: str) -> dict:
    """With "Confirm email" off this returns a session at once; with it on, only the user (no access_token)."""
    return _post(supabase_url, key, "signup", {"email": email, "password": pw, "data": {"full_name": name}})


def profile(session: dict) -> dict:
    """What the app shows about the person: name, email and the GitHub avatar when there is one."""
    user = session.get("user") or {}
    meta = user.get("user_metadata") or {}
    email = user.get("email")
    name = (meta.get("full_name") or meta.get("name") or meta.get("user_name") or (email or "").split("@")[0] or "you")
    avatar = meta.get("avatar_url")
    return {"name": name.strip()[:64], "email": email,
            "avatar": avatar if isinstance(avatar, str) and avatar.startswith("https://") else None}

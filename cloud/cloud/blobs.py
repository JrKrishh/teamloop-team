"""Where files teammates share live, behind short-lived signed links the app uploads to and downloads from directly:

- SupabaseBlobs: a private Supabase Storage bucket (production). Files never pass through the hub, so Vercel's 4.5 MB
  body limit doesn't apply; the bucket's own size limit (25 MB) does. Env: SUPABASE_URL, SUPABASE_SECRET_KEY,
  SHARES_BUCKET (default "shares").
- LocalBlobs: a folder on the hub (development and self-hosted hubs), with the same flow: HMAC-signed links the hub
  serves at /v1/blobs/<token>.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional


class SupabaseBlobs:
    def __init__(self, url: str, key: str, bucket: str = "shares", public_key: str = ""):
        self.url, self.key, self.bucket, self.public_key = url.rstrip("/"), key, bucket, public_key

    def _call(self, method: str, path: str, body: Optional[dict] = None):
        req = urllib.request.Request(f"{self.url}/storage/v1/{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {self.key}", "apikey": self.key,
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
        return json.loads(raw) if raw else {}

    def _obj(self, path: str) -> str:
        return f"{self.bucket}/{urllib.parse.quote(path)}"

    def upload(self, path: str, size: int, base: str = "") -> dict:
        signed = self._call("POST", f"object/upload/sign/{self._obj(path)}")["url"]
        headers = {"x-upsert": "false"} | ({"apikey": self.public_key} if self.public_key else {})
        return {"url": f"{self.url}/storage/v1{signed}", "method": "PUT", "headers": headers}

    def download(self, path: str, seconds: int = 300, base: str = "") -> str:
        signed = self._call("POST", f"object/sign/{self._obj(path)}", {"expiresIn": seconds})["signedURL"]
        return f"{self.url}/storage/v1{signed}"

    def size(self, path: str) -> Optional[int]:
        folder, _, name = path.rpartition("/")
        for o in self._call("POST", f"object/list/{self.bucket}", {"prefix": folder, "search": name, "limit": 10}) or []:
            if o.get("name") == name:
                return int((o.get("metadata") or {}).get("size") or 0)
        return None

    def delete(self, paths: list[str]) -> None:
        if paths:
            self._call("DELETE", f"object/{self.bucket}", {"prefixes": paths})


class LocalBlobs:
    def __init__(self, root: Path, secret: Optional[bytes] = None):
        self.root, self.secret = root, secret or secrets.token_bytes(32)

    def token(self, op: str, path: str, seconds: int) -> str:
        payload = base64.urlsafe_b64encode(json.dumps([op, path, int(time.time()) + seconds]).encode()).decode().rstrip("=")
        sig = hmac.new(self.secret, payload.encode(), hashlib.sha256).hexdigest()[:40]
        return f"{payload}.{sig}"

    def check(self, token: str, op: str) -> Path:
        payload, _, sig = token.partition(".")
        good = hmac.new(self.secret, payload.encode(), hashlib.sha256).hexdigest()[:40]
        if not hmac.compare_digest(sig, good):
            raise PermissionError("That link isn't valid")
        what, path, until = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if what != op or until < time.time():
            raise PermissionError("That link has expired")
        f = (self.root / path).resolve()
        if self.root.resolve() not in f.parents:
            raise PermissionError("That link isn't valid")
        return f

    def upload(self, path: str, size: int, base: str = "") -> dict:
        return {"url": f"{base}/v1/blobs/{self.token('put', path, 7200)}", "method": "PUT", "headers": {}}

    def download(self, path: str, seconds: int = 300, base: str = "") -> str:
        return f"{base}/v1/blobs/{self.token('get', path, seconds)}"

    def size(self, path: str) -> Optional[int]:
        f = self.root / path
        return f.stat().st_size if f.is_file() else None

    def delete(self, paths: list[str]) -> None:
        for p in paths:
            (self.root / p).unlink(missing_ok=True)


def from_env():
    """Supabase Storage when the hub has the secret key; a folder on the hub otherwise, except on serverless hosts,
    where there's no disk to keep files on (sharing then says it isn't set up)."""
    if os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SECRET_KEY"):
        return SupabaseBlobs(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"], os.getenv("SHARES_BUCKET", "shares"),
                             os.getenv("SUPABASE_PUBLISHABLE_KEY", ""))
    if os.getenv("VERCEL"):
        return None
    root = Path(os.getenv("HUB_BLOBS_DIR") or Path(tempfile.gettempdir()) / "teamloop-blobs")
    secret = os.getenv("HUB_BLOB_SECRET")
    return LocalBlobs(root, secret.encode() if secret else None)

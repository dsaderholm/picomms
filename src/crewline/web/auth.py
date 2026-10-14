"""Authentication helpers for the web process (no third-party crypto dependencies)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import time
from pathlib import Path

PBKDF2_ROUNDS = 200_000
SESSION_TTL_S = 12 * 3600


def hash_password(password: str, salt: bytes | None = None) -> dict:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return {"salt": base64.b64encode(salt).decode(), "hash": base64.b64encode(dk).decode(),
            "rounds": PBKDF2_ROUNDS}


def verify_password(password: str, rec: dict) -> bool:
    salt = base64.b64decode(rec["salt"])
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(rec.get("rounds", PBKDF2_ROUNDS)))
    return hmac.compare_digest(dk, base64.b64decode(rec["hash"]))


class AuthStore:
    """Credentials + remote-link tokens, kept in one 0600 JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.data: dict = {}

    def load(self) -> str | None:
        """Load or create. Returns a freshly generated admin password (to show once) or None."""
        first_password = None
        if self.path.exists():
            self.data = json.loads(self.path.read_text())
        else:
            self.data = {}
        if "secret" not in self.data:
            self.data["secret"] = base64.b64encode(os.urandom(32)).decode()
        if "admin" not in self.data:
            first_password = secrets.token_urlsafe(9)
            self.data["admin"] = hash_password(first_password)
        self.data.setdefault("remote_tokens", {})
        self.save()
        return first_password

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2))
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def set_password(self, password: str) -> None:
        if len(password) < 8:
            raise ValueError("password must be at least 8 characters")
        self.data["admin"] = hash_password(password)
        self.data["secret"] = base64.b64encode(os.urandom(32)).decode()   # invalidates old sessions
        self.save()

    def check_password(self, password: str) -> bool:
        return verify_password(password, self.data["admin"])

    # -- sessions (stateless, HMAC-signed) --------------------------------------
    def _key(self) -> bytes:
        return base64.b64decode(self.data["secret"])

    def make_session(self, now: float | None = None) -> str:
        exp = int((now or time.time()) + SESSION_TTL_S)
        body = f"{exp}.{secrets.token_urlsafe(8)}"
        sig = hmac.new(self._key(), body.encode(), hashlib.sha256).hexdigest()
        return f"{body}.{sig}"

    def check_session(self, tok: str | None, now: float | None = None) -> bool:
        if not tok or tok.count(".") != 2:
            return False
        body, _, sig = tok.rpartition(".")
        good = hmac.new(self._key(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, good):
            return False
        try:
            return int(body.split(".")[0]) > (now or time.time())
        except ValueError:
            return False

    # -- remote tokens: one unguessable link per endpoint -------------------------
    def token_for(self, endpoint: str, create: bool = True) -> str | None:
        for t, e in self.data["remote_tokens"].items():
            if e == endpoint:
                return t
        if not create:
            return None
        return self.rotate_token(endpoint)

    def rotate_token(self, endpoint: str) -> str:
        self.data["remote_tokens"] = {t: e for t, e in self.data["remote_tokens"].items() if e != endpoint}
        tok = secrets.token_urlsafe(16)
        self.data["remote_tokens"][tok] = endpoint
        self.save()
        return tok

    def endpoint_for_token(self, tok: str) -> str | None:
        for t, e in self.data["remote_tokens"].items():
            if hmac.compare_digest(t, tok):
                return e
        return None

    def prune(self, valid_endpoints: set[str]) -> None:
        before = len(self.data["remote_tokens"])
        self.data["remote_tokens"] = {t: e for t, e in self.data["remote_tokens"].items() if e in valid_endpoints}
        if len(self.data["remote_tokens"]) != before:
            self.save()


DEFAULT_ALLOWED = ["127.0.0.0/8", "::1/128", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
                   "169.254.0.0/16", "fe80::/10", "fc00::/7"]


def ip_allowed(ip: str | None, networks: list[str]) -> bool:
    """The appliance is LAN-only: refuse clients outside private/loopback ranges."""
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
        if getattr(addr, "ipv4_mapped", None):
            addr = addr.ipv4_mapped
        return any(addr in ipaddress.ip_network(n) for n in networks)
    except ValueError:
        return False


class RateLimiter:
    def __init__(self, limit: int, per_s: float) -> None:
        self.limit, self.per = limit, per_s
        self.hits: dict[str, list[float]] = {}

    def allow(self, key: str, now: float | None = None) -> bool:
        now = now or time.monotonic()
        h = [t for t in self.hits.get(key, []) if now - t < self.per]
        if len(h) >= self.limit:
            self.hits[key] = h
            return False
        h.append(now)
        self.hits[key] = h
        if len(self.hits) > 2000:
            self.hits = {k: v for k, v in self.hits.items() if v and now - v[-1] < self.per}
        return True

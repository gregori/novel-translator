"""Single-password gate and stateless sessions for the web room.

The room is protected by one shared password. Passwords are hashed
with stdlib scrypt, and sessions are stateless signed tokens kept in
an ``HttpOnly`` cookie, so no session table is needed.

The integrator enables the gate by storing an :class:`AuthState` on
``app.state.auth`` and adding :class:`AuthMiddleware` to the app.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import quote, urlsplit

from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from novel_translator.web.routes.support import wants_partial

AUTH_COOKIE = "nt_session"

SESSION_MAX_AGE_SECONDS = 2592000  # 30 days.

_ALLOWLISTED_PATHS = frozenset({"/healthz", "/login", "/static"})
_STATIC_PREFIX = "/static/"

_SCRYPT_N = 16384
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SALT_BYTES = 16


@dataclass(frozen=True, slots=True)
class AuthState:
    """Describe whether the web room requires a password."""

    enabled: bool
    password_hash: str
    secret: bytes


def build_auth_state(
    password_hash: str | None, session_secret: str | None
) -> AuthState:
    """Build the gate state from raw configuration values.

    Disabled only when both values are absent (local development).
    Exactly one value is a misconfiguration and fails closed with
    ValueError, so a half-provisioned server never serves an open
    room. The secret must be at least 16 characters.
    """
    has_password = bool(password_hash and password_hash.strip())
    has_secret = bool(session_secret and session_secret.strip())
    if not has_password and not has_secret:
        return AuthState(enabled=False, password_hash="", secret=b"")
    if not has_password or not has_secret:
        raise ValueError(
            "Auth is half-configured: set both the password hash "
            "and the session secret, or neither for local development."
        )
    assert password_hash is not None
    assert session_secret is not None
    secret = session_secret.strip().encode("utf-8")
    if len(secret) < 16:
        raise ValueError("Session secret must be at least 16 characters.")
    return AuthState(enabled=True, password_hash=password_hash, secret=secret)


def hash_password(password: str) -> str:
    """Hash a password with stdlib scrypt and a fresh salt."""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    params = f"n={_SCRYPT_N},r={_SCRYPT_R},p={_SCRYPT_P}"
    salt_part = base64.b64encode(salt).decode("ascii")
    hash_part = base64.b64encode(digest).decode("ascii")
    return f"scrypt${params}${salt_part}${hash_part}"


def verify_password(password: str, stored: str) -> bool:
    """Check a password against a stored hash, safely failing shut."""
    try:
        prefix, params, salt_part, hash_part = stored.split("$")
        if prefix != "scrypt":
            return False
        options = dict(part.split("=") for part in params.split(","))
        salt = base64.b64decode(salt_part)
        expected = base64.b64decode(hash_part)
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(options["n"]),
            r=int(options["r"]),
            p=int(options["p"]),
            dklen=len(expected),
        )
    except ValueError, KeyError, binascii.Error:
        return False
    return hmac.compare_digest(digest, expected)


def _b64url_encode(raw: bytes) -> str:
    """Encode bytes as unpadded URL-safe base64 text."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    """Decode unpadded URL-safe base64 text back to bytes."""
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def issue_session(
    secret: bytes, max_age_seconds: int = SESSION_MAX_AGE_SECONDS
) -> str:
    """Mint a signed session token expiring after the given age."""
    payload = {"v": 1, "exp": int(time.time()) + max_age_seconds}
    encoded = _b64url_encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    )
    signature = hmac.new(
        secret, encoded.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{encoded}.{_b64url_encode(signature)}"


def validate_session(value: str, secret: bytes) -> bool:
    """Accept only tokens with a valid signature and live expiry."""
    try:
        encoded, signature = value.split(".")
        expected = hmac.new(
            secret, encoded.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(_b64url_encode(expected), signature):
            return False
        decoded: Any = json.loads(_b64url_decode(encoded).decode("utf-8"))
    except ValueError:
        return False
    if not isinstance(decoded, dict):
        return False
    payload = cast("dict[str, Any]", decoded)
    if payload.get("v") != 1:
        return False
    expiry: Any = payload.get("exp")
    if isinstance(expiry, bool) or not isinstance(expiry, int):
        return False
    return expiry > int(time.time())


def safe_next(value: str) -> str:
    """Keep only internal redirect targets, dropping anything else."""
    if not value or "\\" in value:
        return ""
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        return ""
    path = parts.path
    if not path.startswith("/") or path.startswith("//"):
        return ""
    if any(char.isspace() or ord(char) < 32 for char in value):
        return ""
    if parts.query:
        return f"{path}?{parts.query}"
    return path


class LoginThrottle:
    """Count recent login failures per key in process memory.

    A single replica serves the web room, so process memory is
    sufficient: every login attempt reaches the same counter.
    """

    def __init__(
        self,
        limit: int = 10,
        window_seconds: int = 300,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._failures: dict[str, list[float]] = {}

    def allowed(self, key: str) -> bool:
        """Report whether one more attempt from the key may proceed."""
        return len(self._recent(key)) < self._limit

    def note_failure(self, key: str) -> None:
        """Record a failed login attempt from the key."""
        self._failures.setdefault(key, []).append(self._clock())
        fresh = self._recent(key)
        if len(fresh) > self._limit:
            self._failures[key] = fresh[-self._limit :]
        if len(self._failures) > 1024:
            self._drop_stale_keys()

    def note_success(self, key: str) -> None:
        """Forget past failures after a successful login."""
        self._failures.pop(key, None)

    def clear(self) -> None:
        """Drop every counter (tests and operator resets)."""
        self._failures.clear()

    def _recent(self, key: str) -> list[float]:
        """Return the key's failures inside the current window."""
        cutoff = self._clock() - self._window
        fresh = [when for when in self._failures.get(key, []) if when > cutoff]
        if fresh:
            self._failures[key] = fresh
        else:
            self._failures.pop(key, None)
        return fresh

    def _drop_stale_keys(self) -> None:
        """Prune idle keys so the table stays bounded."""
        cutoff = self._clock() - self._window
        stale = [
            key
            for key, whens in self._failures.items()
            if not any(when > cutoff for when in whens)
        ]
        for key in stale:
            del self._failures[key]


class AuthMiddleware(BaseHTTPMiddleware):
    """Require a valid session cookie on every non-public route."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        auth = getattr(request.app.state, "auth", None)
        if not isinstance(auth, AuthState) or not auth.enabled:
            return await call_next(request)
        path = request.url.path
        if path in _ALLOWLISTED_PATHS or path.startswith(_STATIC_PREFIX):
            return await call_next(request)
        token = request.cookies.get(AUTH_COOKIE, "")
        if token and validate_session(token, auth.secret):
            return await call_next(request)
        if wants_partial(request):
            return Response(
                status_code=401,
                headers={"HX-Redirect": "/login"},
            )
        target = request.url.path
        if request.url.query:
            target += f"?{request.url.query}"
        return RedirectResponse(
            f"/login?next={quote(target, safe='')}",
            status_code=303,
        )

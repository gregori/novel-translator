"""Tests for the single-password gate and cookie sessions."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient

from novel_translator.web.app import TEMPLATES
from novel_translator.web.auth import (
    AUTH_COOKIE,
    AuthMiddleware,
    AuthState,
    build_auth_state,
    hash_password,
    issue_session,
    safe_next,
    validate_session,
    verify_password,
)
from novel_translator.web.routes.auth import (
    login_throttle,
)
from novel_translator.web.routes.auth import (
    router as auth_router,
)

PASSWORD = "correct-horse-battery-staple"
SECRET = "test-session-secret-0123456789"


def build_state(
    *, password: str = PASSWORD, secret: str = SECRET
) -> AuthState:
    """Compose an enabled gate state from plain values."""
    return build_auth_state(hash_password(password), secret)


def build_client(state: AuthState) -> TestClient:
    """Compose a minimal app with the gate and one private route."""
    login_throttle.clear()
    app = FastAPI()
    app.state.templates = Jinja2Templates(directory=str(TEMPLATES))
    app.state.auth = state

    @app.get("/private")
    def private() -> PlainTextResponse:
        return PlainTextResponse("private-ok")

    app.include_router(auth_router)
    app.add_middleware(AuthMiddleware)
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def client() -> TestClient:
    """Serve a fresh enabled gate with an empty throttle."""
    return build_client(build_state())


def test_password_roundtrip() -> None:
    """A fresh hash verifies against the password that made it."""
    stored = hash_password(PASSWORD)
    assert stored.startswith("scrypt$n=16384,r=8,p=1$")
    assert verify_password(PASSWORD, stored)
    assert not verify_password("wrong-password", stored)


def test_verify_rejects_malformed_hashes() -> None:
    """Garbage, foreign schemes, and tampered hashes fail shut."""
    assert not verify_password(PASSWORD, "")
    assert not verify_password(PASSWORD, "not-a-hash")
    assert not verify_password(PASSWORD, "md5$salt$hash")
    stored = hash_password(PASSWORD)
    assert not verify_password(PASSWORD, stored[:-4] + "AAAA")


def test_session_roundtrip_tamper_and_expiry() -> None:
    """Tokens validate until tampered with or past their expiry."""
    secret = SECRET.encode("utf-8")
    token = issue_session(secret)
    assert validate_session(token, secret)
    assert not validate_session(token, b"another-secret-value")
    assert not validate_session(token + "x", secret)
    assert not validate_session("garbage", secret)
    expired = issue_session(secret, max_age_seconds=-10)
    assert not validate_session(expired, secret)


def test_build_auth_state_needs_both_values() -> None:
    """Absent configuration disables the gate; half raises fail-closed."""
    assert not build_auth_state(None, None).enabled
    assert not build_auth_state("", "   ").enabled
    with pytest.raises(ValueError):
        build_auth_state(None, SECRET)
    with pytest.raises(ValueError):
        build_auth_state(hash_password(PASSWORD), None)
    with pytest.raises(ValueError):
        build_auth_state("", SECRET)
    with pytest.raises(ValueError):
        build_auth_state(hash_password(PASSWORD), "   ")
    assert build_state().enabled


def test_build_auth_state_rejects_short_secret() -> None:
    """Secrets under 16 decoded bytes raise instead of weakening."""
    with pytest.raises(ValueError):
        build_auth_state(hash_password(PASSWORD), "short")


def test_safe_next_keeps_only_internal_paths() -> None:
    """Internal paths pass through; absolute URLs are dropped."""
    assert safe_next("/novels/novel/chapters/1") == (
        "/novels/novel/chapters/1"
    )
    assert safe_next("/a?b=c") == "/a?b=c"
    assert safe_next("https://evil.example/") == ""
    assert safe_next("//evil.example/") == ""
    assert safe_next("javascript:alert(1)") == ""
    assert safe_next("") == ""


def test_login_page_renders_password_form(client: TestClient) -> None:
    """The sign-in page shows a password-only form."""
    response = client.get("/login")
    assert response.status_code == 200
    assert 'name="password"' in response.text
    assert 'name="next"' in response.text


def test_login_success_sets_cookie_and_redirects(
    client: TestClient,
) -> None:
    """The right password redirects and mints a session cookie."""
    response = client.post("/login", data={"password": PASSWORD, "next": ""})
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert AUTH_COOKIE in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]


def test_login_success_grants_private_access(
    client: TestClient,
) -> None:
    """The minted cookie opens protected routes."""
    client.post("/login", data={"password": PASSWORD})
    response = client.get("/private")
    assert response.status_code == 200
    assert response.text == "private-ok"


def test_login_success_honors_safe_next(client: TestClient) -> None:
    """Internal next targets survive login; external ones do not."""
    response = client.post(
        "/login",
        data={"password": PASSWORD, "next": "/private?x=1"},
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/private?x=1"
    response = client.post(
        "/login",
        data={"password": PASSWORD, "next": "https://evil/"},
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_login_failure_stays_generic_without_cookie(
    client: TestClient,
) -> None:
    """A wrong password re-renders the form without saying more."""
    response = client.post("/login", data={"password": "wrong-password"})
    assert response.status_code == 200
    assert "Incorrect password" in response.text
    assert AUTH_COOKIE not in response.headers.get("set-cookie", "")
    assert hash_password(PASSWORD) not in response.text


def test_protected_navigation_redirects_to_login(
    client: TestClient,
) -> None:
    """Plain navigation without a cookie bounces to the form."""
    response = client.get("/private")
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=%2Fprivate"


def test_protected_partial_returns_unauthorized(
    client: TestClient,
) -> None:
    """Fragments ask for a client-side redirect instead of HTML."""
    for headers in (
        {"hx-request": "true"},
        {"x-requested-with": "fetch"},
    ):
        response = client.get("/private", headers=headers)
        assert response.status_code == 401
        assert response.headers["hx-redirect"] == "/login"


def test_logout_expires_the_cookie(client: TestClient) -> None:
    """Logout clears the session and returns to the sign-in form."""
    client.post("/login", data={"password": PASSWORD})
    response = client.post("/logout")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert AUTH_COOKIE in response.headers["set-cookie"]
    assert "Max-Age=0" in response.headers["set-cookie"]


def test_throttle_blocks_after_eleven_failures(
    client: TestClient,
) -> None:
    """Ten failures render the form; the eleventh is rejected."""
    statuses = [
        client.post("/login", data={"password": "wrong-password"}).status_code
        for _ in range(11)
    ]
    assert statuses == [200] * 10 + [429]
    assert (
        "Too many attempts"
        in client.post("/login", data={"password": PASSWORD}).text
    )


def test_successful_login_resets_the_throttle(
    client: TestClient,
) -> None:
    """A success forgives earlier failures from the same client."""
    for _ in range(9):
        client.post("/login", data={"password": "nope"})
    assert (
        client.post("/login", data={"password": PASSWORD}).status_code == 303
    )
    statuses = [
        client.post("/login", data={"password": "nope"}).status_code
        for _ in range(9)
    ]
    assert statuses == [200] * 9


def test_disabled_gate_leaves_everything_open() -> None:
    """Without configuration no route asks for a session."""
    client = build_client(
        AuthState(enabled=False, password_hash="", secret=b"")
    )
    assert client.get("/private").status_code == 200
    response = client.get("/private", headers={"hx-request": "true"})
    assert response.status_code == 200

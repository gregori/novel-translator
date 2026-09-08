"""Login and logout routes for the single-password gate.

These routes only translate HTTP into calls on web.auth helpers;
no password, hashing, or session rule lives in this module.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from novel_translator.web.auth import (
    AUTH_COOKIE,
    SESSION_MAX_AGE_SECONDS,
    AuthState,
    LoginThrottle,
    issue_session,
    safe_next,
    verify_password,
)

router = APIRouter()

login_throttle = LoginThrottle()

_DISABLED = AuthState(enabled=False, password_hash="", secret=b"")

_INVALID_MESSAGE = "Incorrect password. Try again."
_THROTTLED_MESSAGE = "Too many attempts. Try again later."


def _auth_state(request: Request) -> AuthState:
    """Read the gate state, treating a missing state as disabled."""
    auth = getattr(request.app.state, "auth", None)
    if isinstance(auth, AuthState):
        return auth
    return _DISABLED


def _client_ip(request: Request) -> str:
    """Identify the caller for throttling purposes."""
    if request.client is None:
        return "unknown"
    return request.client.host


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "") -> HTMLResponse:
    """Show the single-password sign-in form."""
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": None, "next": safe_next(next)},
    )


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    password: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "",
) -> Response:
    """Check the password and mint a session cookie on success."""
    templates = request.app.state.templates
    auth = _auth_state(request)
    target = safe_next(next)
    context = {"error": _INVALID_MESSAGE, "next": target}
    ip = _client_ip(request)
    if not login_throttle.allowed(ip):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": _THROTTLED_MESSAGE, "next": target},
            status_code=429,
        )
    if (
        auth.enabled
        and password
        and verify_password(password, auth.password_hash)
    ):
        login_throttle.note_success(ip)
        response = RedirectResponse(target or "/", status_code=303)
        response.set_cookie(
            AUTH_COOKIE,
            issue_session(auth.secret),
            max_age=SESSION_MAX_AGE_SECONDS,
            path="/",
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
        )
        return response
    login_throttle.note_failure(ip)
    return templates.TemplateResponse(
        request, "login.html", context, status_code=200
    )


@router.post("/logout")
def logout() -> RedirectResponse:
    """Expire the session cookie and return to the sign-in form."""
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(AUTH_COOKIE, path="/")
    return response

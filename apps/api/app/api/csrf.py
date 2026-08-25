"""Reusable double-submit CSRF dependency for state-changing endpoints.

The CSRF token lives in a host-only, non-HttpOnly cookie the frontend can
read; the session cookie stays HttpOnly. State-changing requests must echo
the token in the X-CSRF-Token header; cookie and header are compared in
constant time. Future Connection POST/PUT/PATCH/DELETE endpoints should
depend on `require_csrf` too.
"""

from fastapi import HTTPException, Request, Response, status

from app.core.config import get_settings
from app.core.security import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    csrf_tokens_match,
    generate_csrf_token,
)


def require_csrf(request: Request) -> None:
    cookie = request.cookies.get(CSRF_COOKIE_NAME)
    header = request.headers.get(CSRF_HEADER_NAME)
    if not cookie or not header or not csrf_tokens_match(cookie, header):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token missing or invalid"
        )


def set_csrf_cookie(response: Response) -> str:
    settings = get_settings()
    token = generate_csrf_token()
    response.set_cookie(
        CSRF_COOKIE_NAME,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=False,  # frontend must read it to echo in the header
        samesite="lax",
        secure=settings.environment == "production",
        path="/",
    )
    return token


def clear_csrf_cookie(response: Response) -> None:
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")

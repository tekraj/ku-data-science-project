from __future__ import annotations

from typing import Any, Iterator

from fastapi import Cookie, Header, HTTPException, status
from sqlalchemy.orm import Session

from nepse_common.config import load_app_config
from nepse_common.db.session import session_scope

from services.auth_service import AuthService

_JWT_COOKIE_NAME = "nepse_access_token"


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a SQLAlchemy Session bound to the app's database config."""
    config = load_app_config()
    with session_scope(config.database) as session:
        yield session


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1]


def get_current_claims(
    authorization: str | None = Header(default=None),
    access_cookie: str | None = Cookie(default=None, alias=_JWT_COOKIE_NAME),
) -> dict[str, Any]:
    """FastAPI dependency requiring a valid bearer token or auth cookie.

    Mirrors the old monolith's _require_auth: extract bearer token OR cookie,
    401 if neither is present, then decode/validate via AuthService.
    """
    token = _extract_bearer_token(authorization) or access_cookie
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authorization")

    config = load_app_config()
    auth_service = AuthService(config.auth)
    return auth_service.decode_jwt(token)

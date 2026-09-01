from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from nepse_common.config import load_app_config
from nepse_common.schemas.auth import SignInRequest

from deps import get_current_claims, get_db
from services.auth_service import AuthService

router = APIRouter()

_JWT_COOKIE_NAME = "nepse_access_token"


@router.post("/signin")
def auth_signin(payload: SignInRequest, response: Response, db: Session = Depends(get_db)) -> dict[str, Any]:
    config = load_app_config()
    auth_service = AuthService(config.auth, db)

    token, user = auth_service.authenticate(payload.email, payload.password)

    response.set_cookie(
        key=_JWT_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=config.auth.cookie_secure,
        samesite="lax",
        max_age=config.auth.jwt_ttl_minutes * 60,
        path="/",
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "email": user.email,
            "display_name": user.display_name or user.email,
        },
    }


@router.post("/logout")
def auth_logout(response: Response) -> dict[str, str]:
    response.delete_cookie(key=_JWT_COOKIE_NAME, path="/")
    return {"message": "Signed out"}


@router.get("/me")
def auth_me(claims: dict[str, Any] = Depends(get_current_claims)) -> dict[str, Any]:
    email = claims.get("sub", "")
    return {
        "authenticated": True,
        "user": {
            "email": email,
            "display_name": claims.get("name") or email,
        },
    }

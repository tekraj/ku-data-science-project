from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from nepse_common.config import AuthConfig
from nepse_common.models import AdminUser
from nepse_common.security import verify_password

_JWT_ALGO = "HS256"


class AuthService:
    """DB-backed admin login. Credentials live in admin_users (bcrypt hash);
    there is no signup endpoint -- accounts are created only via manage.py create-admin.
    """

    def __init__(self, auth_config: AuthConfig, db: Session | None = None) -> None:
        self._auth_config = auth_config
        self._db = db

    def create_jwt(self, email: str, display_name: str | None = None) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": email,
            "name": display_name,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=self._auth_config.jwt_ttl_minutes)).timestamp()),
        }
        return jwt.encode(payload, self._auth_config.jwt_secret, algorithm=_JWT_ALGO)

    def decode_jwt(self, token: str) -> dict[str, Any]:
        try:
            return jwt.decode(token, self._auth_config.jwt_secret, algorithms=[_JWT_ALGO])
        except jwt.PyJWTError as e:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from e

    def authenticate(self, email: str, password: str) -> tuple[str, AdminUser]:
        """Validates credentials against admin_users.

        Returns (signed_jwt, user) on success or raises HTTPException(401) on
        mismatch (invalid email, wrong password, or an inactive account) --
        the same generic error either way so login failures don't reveal
        which part was wrong or whether the account exists.
        """
        if self._db is None:
            raise RuntimeError("AuthService.authenticate() requires a database session")

        normalized_email = (email or "").strip().lower()
        supplied_password = password or ""

        user = self._db.execute(
            select(AdminUser).where(AdminUser.email == normalized_email)
        ).scalar_one_or_none()

        if (
            user is None
            or not user.is_active
            or not verify_password(supplied_password, user.password_hash)
        ):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

        return self.create_jwt(user.email, user.display_name), user

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import bcrypt
from fastapi import Cookie, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from config import settings
from db.database import get_db
from db.models import User
from schemas.auth import UserOut

ACCESS_COOKIE = "migr8_access"
REFRESH_COOKIE = "migr8_refresh"
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def user_out(user: User) -> UserOut:
    return UserOut(
        id=str(user.id),
        fullName=user.full_name,
        email=user.email,
        role=user.role or "member",
    )


def _encode(user_id: str, token_type: str, expire: datetime) -> str:
    payload = {"sub": user_id, "typ": token_type, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    return _encode(user_id, "access", expire)


def create_refresh_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_expire_days)
    return _encode(user_id, "refresh", expire)


def decode_token(token: str, expected_type: str = "access") -> str:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user_id = payload.get("sub")
        token_type = payload.get("typ", "access")
        if not user_id or token_type != expected_type:
            raise JWTError()
        return str(user_id)
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")


def _cookie_kwargs() -> dict:
    samesite = (settings.cookie_samesite or "lax").lower()
    if samesite not in ("lax", "strict", "none"):
        samesite = "lax"
    secure = bool(settings.cookie_secure) or samesite == "none"
    return {
        "httponly": True,
        "secure": secure,
        "samesite": samesite,
        "path": "/",
    }


def set_auth_cookies(response: Response, user_id: str) -> str:
    access = create_access_token(user_id)
    refresh = create_refresh_token(user_id)
    kwargs = _cookie_kwargs()
    response.set_cookie(
        ACCESS_COOKIE,
        access,
        max_age=settings.jwt_expire_minutes * 60,
        **kwargs,
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh,
        max_age=settings.jwt_refresh_expire_days * 24 * 60 * 60,
        **kwargs,
    )
    return access


def clear_auth_cookies(response: Response) -> None:
    kwargs = _cookie_kwargs()
    response.delete_cookie(ACCESS_COOKIE, path=kwargs["path"])
    response.delete_cookie(REFRESH_COOKIE, path=kwargs["path"])


def _token_from_request(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials],
    access_cookie: Optional[str],
) -> str:
    if access_cookie:
        return access_cookie
    if credentials and credentials.credentials:
        return credentials.credentials
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")


def load_user(db: Session, user_id: str) -> User:
    try:
        uid = UUID(user_id)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = db.get(User, uid)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    if user.is_active is False:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account is disabled")
    return user


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    access_cookie: Optional[str] = Cookie(default=None, alias=ACCESS_COOKIE),
    db: Session = Depends(get_db),
) -> User:
    token = _token_from_request(request, credentials, access_cookie)
    user_id = decode_token(token, "access")
    user = load_user(db, user_id)
    request.state.user_id = str(user.id)
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if (current_user.role or "member") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return current_user


def maybe_promote_admin(user: User) -> None:
    admin_email = (settings.admin_email or "").strip().lower()
    if admin_email and user.email == admin_email and user.role != "admin":
        user.role = "admin"

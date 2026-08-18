from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from auth import (
    REFRESH_COOKIE,
    clear_auth_cookies,
    create_access_token,
    decode_token,
    get_current_user,
    hash_password,
    load_user,
    maybe_promote_admin,
    set_auth_cookies,
    user_out,
    verify_password,
)
from db.database import get_db
from db.models import User, UserInvite
from rate_limit import enforce_rate_limit
from schemas import AuthResponse, LoginRequest, RegisterRequest, UserOut
from services import app_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _auth_response(user: User, token: str | None = None) -> AuthResponse:
    return AuthResponse(user=user_out(user), token=token)


@router.post("/register", response_model=AuthResponse)
def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    enforce_rate_limit(request, limit=8, window_seconds=60)
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")

    if app_settings.invite_only(db):
        invite = db.query(UserInvite).filter(UserInvite.email == payload.email).first()
        if not invite or invite.used_at is not None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Registration is invite-only. Ask an admin to invite this email.",
            )

    user = User(
        full_name=payload.fullName,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role="member",
        is_active=True,
    )
    maybe_promote_admin(user)
    db.add(user)
    if app_settings.invite_only(db):
        invite = db.query(UserInvite).filter(UserInvite.email == payload.email).first()
        if invite:
            from datetime import datetime, timezone
            invite.used_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    token = set_auth_cookies(response, str(user.id))
    return _auth_response(user, token)


@router.post("/login", response_model=AuthResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    enforce_rate_limit(request, limit=10, window_seconds=60)
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if user.is_active is False:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account is disabled")
    maybe_promote_admin(user)
    db.commit()

    token = set_auth_cookies(response, str(user.id))
    return _auth_response(user, token)


@router.post("/refresh", response_model=AuthResponse)
def refresh(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    user_id = decode_token(raw, "refresh")
    user = load_user(db, user_id)
    token = set_auth_cookies(response, str(user.id))
    return _auth_response(user, token)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return user_out(current_user)


@router.post("/logout")
def logout(response: Response, current_user: User = Depends(get_current_user)):
    clear_auth_cookies(response)
    return {"message": "Logged out", "userId": str(current_user.id)}

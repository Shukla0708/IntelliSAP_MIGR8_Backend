from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import User
from auth import hash_password, verify_password, create_access_token, get_current_user
from schemas import RegisterRequest, LoginRequest, AuthResponse, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=AuthResponse)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")

    user = User(
        full_name=payload.fullName,
        email=payload.email,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(str(user.id))
    return AuthResponse(
        token=token,
        user=UserOut(id=str(user.id), fullName=user.full_name, email=user.email),
    )


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    token = create_access_token(str(user.id))
    return AuthResponse(
        token=token,
        user=UserOut(id=str(user.id), fullName=user.full_name, email=user.email),
    )


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return UserOut(id=str(current_user.id), fullName=current_user.full_name, email=current_user.email)


@router.post("/logout")
def logout(current_user: User = Depends(get_current_user)):
    # Stateless JWT: client discards the token. Endpoint confirms the session was valid.
    return {"message": "Logged out", "userId": str(current_user.id)}


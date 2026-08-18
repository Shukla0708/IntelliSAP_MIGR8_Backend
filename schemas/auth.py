from pydantic import BaseModel, field_validator
import re

_PASSWORD_MIN = 8


class RegisterRequest(BaseModel):
    fullName: str
    email: str
    password: str

    @field_validator("fullName", "email", "password")
    @classmethod
    def not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be empty")
        return cleaned

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        if "@" not in value or "." not in value.split("@")[-1]:
            raise ValueError("must be a valid email address (e.g. you@company.com)")
        return value.lower()

    @field_validator("password")
    @classmethod
    def strong_enough(cls, value: str) -> str:
        if len(value) < _PASSWORD_MIN:
            raise ValueError(f"must be at least {_PASSWORD_MIN} characters")
        if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
            raise ValueError("must include a letter and a number")
        return value


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email", "password")
    @classmethod
    def not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be empty")
        return cleaned

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class UserOut(BaseModel):
    id: str
    fullName: str
    email: str
    role: str = "member"

    class Config:
        from_attributes = True


class AuthResponse(BaseModel):
    user: UserOut
    token: str | None = None

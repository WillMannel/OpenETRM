import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.common.enums import UserRole


class UserRegister(BaseModel):
    """Self-service signup -- always lands as VIEWER. Elevated roles are granted by an
    admin via POST /auth/users, never chosen by the registrant."""

    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    role: UserRole = UserRole.VIEWER


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    username: str
    email: str
    role: UserRole
    is_active: bool
    created_at: datetime


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

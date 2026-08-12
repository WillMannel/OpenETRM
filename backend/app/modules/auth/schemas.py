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
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    # Optional: revoking the refresh token too (not just the access token being used
    # to authenticate this call) is what actually ends the session -- an access token
    # left un-revoked would still work until its own (short) expiry either way, but a
    # refresh token left un-revoked could mint fresh access tokens indefinitely.
    refresh_token: str | None = None


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    expires_at: datetime | None = None


class ApiKeyCreated(BaseModel):
    """Returned only from the create endpoint -- the one and only time the raw key is
    ever available. Store it now; it can't be retrieved again, only revoked."""

    id: uuid.UUID
    name: str
    key_prefix: str
    api_key: str
    expires_at: datetime | None
    created_at: datetime


class ApiKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    key_prefix: str
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.enums import UserRole
from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(String(20), nullable=False, default=UserRole.VIEWER)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Set only for users provisioned via OIDC/Entra ID SSO (see app.modules.auth.oidc)
    # -- the provider's `sub` claim, the one value every OIDC issuer guarantees is
    # stable and unique per user, unlike email (can change/be reused).
    oidc_subject: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RefreshToken(Base):
    """A long-lived, single-use, rotating credential issued alongside every access
    token (see app.modules.auth.security.generate_refresh_token /
    AuthService.authenticate). POST /auth/refresh exchanges a valid, unexpired,
    unrevoked refresh token for a new access token *and* a new refresh token,
    revoking this one in the same transaction (`replaced_by_id` points at its
    successor) -- so a refresh token can only ever be used once. Reusing an already-
    rotated token is exactly the signature of a stolen token being used alongside the
    legitimate client; AuthService.refresh treats that as cause to revoke the entire
    chain (see its docstring), not just reject the one request.

    Same storage discipline as ApiKey: only `hashed_token` (SHA-256) is persisted, the
    raw value is shown to the client exactly once."""

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    hashed_token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("refresh_tokens.id"), nullable=True
    )


class ApiKey(Base):
    """A machine-to-machine credential for a *service-account* User (an ordinary User
    row -- typically VIEWER, for a read-only integration like a BI/pipeline tool pulling
    from /export or the reporting views) -- not a separate principal type, so it rides
    every existing RBAC/audit code path unchanged: get_current_user resolves an API key
    to the same User a JWT would.

    Only `hashed_key` (a SHA-256 digest) is stored; the raw key is shown to the caller
    exactly once, at creation, and is unrecoverable after that. SHA-256, not bcrypt: an
    API key is a 256-bit random token (see security.generate_api_key), not a
    human-chosen password -- bcrypt's deliberate slowness defends against brute-forcing
    a *low-entropy* secret, which costs real latency on every request for no benefit
    against a secret an attacker can't feasibly guess either way."""

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # First few characters of the full key, e.g. "oetrm_ab12" -- shown in list views so
    # an admin can tell keys apart without ever seeing the full secret again.
    key_prefix: Mapped[str] = mapped_column(String(14), nullable=False)
    hashed_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(lazy="joined", foreign_keys=[user_id])

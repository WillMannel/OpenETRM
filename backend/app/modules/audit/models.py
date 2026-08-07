import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):
    """A generic, append-only change log. Any entity type can write here (today:
    trades) via app.modules.audit.service.record_audit_event -- entity_type/entity_id
    are a loose reference rather than an FK, deliberately, so this table doesn't need
    to know about every module that might want to be audited."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # JSON on Postgres, TEXT-backed JSON on SQLite -- JSONB specifically isn't portable,
    # plain JSON is (SQLAlchemy compiles it appropriately per dialect).
    before: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
    after: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)

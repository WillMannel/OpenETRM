import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    action: str
    actor_user_id: uuid.UUID | None
    occurred_at: datetime
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    note: str | None

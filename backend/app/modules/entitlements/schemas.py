import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DeskCreate(BaseModel):
    name: str
    description: str | None = None


class DeskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str | None


class BookDeskAssign(BaseModel):
    desk_id: uuid.UUID | None  # None un-assigns the book, making it unrestricted again


class BookMembershipCreate(BaseModel):
    user_id: uuid.UUID


class BookMembershipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    book_id: uuid.UUID
    user_id: uuid.UUID
    granted_by_user_id: uuid.UUID | None
    granted_at: datetime

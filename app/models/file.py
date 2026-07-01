import uuid
from datetime import datetime
from enum import StrEnum

from sqlmodel import Field, SQLModel

from app.models.timestamp import TimestampMixin


class FileStatus(StrEnum):
    PENDING = "pending"
    SAVED = "clean"
    INFECTED = "infected"

class FileObject(TimestampMixin, table=True):
    id: uuid.UUID = Field(primary_key=True)
    status: FileStatus = Field(default=FileStatus.PENDING)
    owner_id: uuid.UUID = Field(foreign_key="user.id", index=True, nullable=False)
    storage_key: str = Field(unique=True)
    original_filename: str
    content_type: str
    size_bytes: int
    checksum: str = Field(index=True, max_length=64)

class FilePublic(SQLModel):
    id: uuid.UUID
    original_filename: str
    content_type: str
    size_bytes: int
    status: FileStatus
    created_at: datetime

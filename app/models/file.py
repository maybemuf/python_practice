from enum import Enum
import uuid
from sqlmodel import Field

from app.models.timestamp import TimestampMixin

class FileStatus(str, Enum):
    PENDING = "pending"
    SAVED = "clean"
    INFECTED = "infected"

class FileObject(TimestampMixin, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    status: FileStatus = Field(default=FileStatus.PENDING)
    owner_id: uuid.UUID = Field(foreign_key="user.id", index=True, nullable=False)
    storage_key: str = Field(unique=True)
    original_filename: str
    content_type: str
    size_bytes: int
    checksum: str = Field(index=True, max_length=64)

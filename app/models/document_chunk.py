import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column
from sqlmodel import Field, SQLModel

from app.models.timestamp import TimestampMixin

EMBEDDING_DIM = 384

class DocumentChunk(TimestampMixin, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    file_id: uuid.UUID = Field(
        foreign_key="fileobject.id", index=True, nullable=False, ondelete="CASCADE"
    )
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", index=True, nullable=False, ondelete="CASCADE"
    )
    chunk_index: int
    content: str
    embedding: list[float] = Field(sa_column=Column(Vector(EMBEDDING_DIM), nullable=False))
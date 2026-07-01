import uuid
from datetime import datetime

from sqlalchemy import DateTime
from sqlmodel import Field

from app.models.timestamp import TimestampMixin


class RefreshToken(TimestampMixin, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id", index=True, nullable=False)
    token_hash: str = Field(index=True, unique=True, nullable=False)
    expires_at: datetime = Field(sa_type=DateTime(timezone=True), nullable=False)
    revoked_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
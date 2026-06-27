from datetime import datetime
import uuid
from pydantic import BaseModel, ConfigDict, EmailStr, field_validator
from sqlmodel import SQLModel, Field

from app.models.timestamp import TimestampMixin
from app.utils import validate_password

class UserBase(SQLModel):
    email: EmailStr = Field(index=True, unique=True)
    username: str = Field(index=True, max_length=30, min_length=3)

class User(UserBase, TimestampMixin, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    password_hash: str

class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return validate_password(v)

class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

class AuthResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserPublic

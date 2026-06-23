from pydantic import BaseModel, ConfigDict, EmailStr, field_validator
from sqlmodel import SQLModel, Field

class UserBase(SQLModel):
    email: EmailStr = Field(index=True, unique=True)
    username: str = Field(index=True, max_length=30, min_length=3)

class User(UserBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    password_hash: str

class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain an uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain a lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain a digit")
        return v

class UserPublic(UserBase):
    id: int

class AuthResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    access_token: str
    token_type: str = "bearer"
    user: UserPublic

from pydantic import BaseModel, Field, field_validator

from app.utils import validate_password

class ChangePasswordBody(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return validate_password(v)
from datetime import datetime, timedelta
from enum import Enum
import hashlib
import hmac
from time import timezone
from typing import Annotated
import uuid

from sqlmodel import Field, SQLModel

from app.settings import settings
from app.models.timestamp import TimestampMixin

OtpRawCodeStr = Annotated[str, Field(min_length=6, max_length=6)]
def hash_otp(raw_code: str) -> str:
    return hmac.new(settings.OTP_PEPPER, raw_code.encode(), hashlib.sha256).hexdigest()

class OTPType(Enum, str):
    EMAIL_VERIFICATION = "email-verification"
    PASSWORD_RECOVERY = "password-recovery"

class OTPRequest(SQLModel, TimestampMixin, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id", index=True, nullable=False)
    code_hash: str
    type: OTPType
    expires_at: datetime = Field(nullable=False)
    consumed_at: datetime | None = Field(default=None)
    invalidated_at: datetime | None = Field(default=None)

    @classmethod
    def issue(cls, raw_code: OtpRawCodeStr, user_id: uuid.UUID, type: OTPType, ttl: timedelta = timedelta(minutes=10)) -> "OTPRequest":
        now = datetime.now(timezone.utc)
        return cls(
            user_id = user_id,
            code_hash = hash_otp(raw_code),
            type = type,
            expires_at = now + ttl,
        )

    def verify(self, code: OtpRawCodeStr) -> bool:
        return hmac.compare_digest(hash_otp(code), self.code_hash)

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expires_at
 
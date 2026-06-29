from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import hmac
from typing import Annotated
import uuid

from sqlalchemy import DateTime
from sqlmodel import Field

from app.settings import settings
from app.models.timestamp import TimestampMixin

OtpRawCodeStr = Annotated[str, Field(min_length=6, max_length=6, regex=r"^\d{6}$")]

def hash_otp(raw_code: str) -> str:
    return hmac.new(settings.OTP_PEPPER.encode(), raw_code.encode(), hashlib.sha256).hexdigest()

class OTPType(str, Enum):
    EMAIL_VERIFICATION = "email-verification"
    PASSWORD_RECOVERY = "password-recovery"

class OTPRequest(TimestampMixin, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id", index=True, nullable=False)
    code_hash: str
    otp_type: OTPType
    expires_at: datetime = Field(sa_type=DateTime(timezone=True), nullable=False)
    consumed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    invalidated_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))

    @classmethod
    def issue(cls, raw_code: OtpRawCodeStr, user_id: uuid.UUID, otp_type: OTPType, ttl: timedelta = timedelta(minutes=10)) -> "OTPRequest":
        now = datetime.now(timezone.utc)
        return cls(
            user_id = user_id,
            code_hash = hash_otp(raw_code),
            otp_type = otp_type,
            expires_at = now + ttl,
        )

    def verify(self, code: OtpRawCodeStr) -> bool:
        return hmac.compare_digest(hash_otp(code), self.code_hash)

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expires_at
 
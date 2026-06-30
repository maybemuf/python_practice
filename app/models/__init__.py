from app.models.user import (
    User,          # the table — this import is what registers it in metadata
    UserBase,
    UserCreate,
    UserPublic,
    AuthResponse,
)
from app.models.refresh_token import RefreshToken  # registers the table in metadata
from app.models.otp import OTPRequest, OTPType      # registers the table in metadata
from app.models.file import FileObject, FileStatus, FilePublic  # registers the table in metadata

__all__ = [
    "User",
    "UserBase",
    "UserCreate",
    "UserPublic",
    "AuthResponse",
    "RefreshToken",
    "OTPRequest",
    "OTPType",
    "FileObject",
    "FileStatus",
    "FilePublic",
]
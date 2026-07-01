from app.models.file import FileObject, FilePublic, FileStatus  # registers the table in metadata
from app.models.otp import OTPRequest, OTPType  # registers the table in metadata
from app.models.refresh_token import RefreshToken  # registers the table in metadata
from app.models.user import (
    AuthResponse,
    User,  # the table — this import is what registers it in metadata
    UserBase,
    UserCreate,
    UserPublic,
)

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
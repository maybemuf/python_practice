from enum import StrEnum

from pydantic import BaseModel


class ApiExceptionType(StrEnum):
    INTERNAL_ERROR = "internal-error"
    INVALID_CREDENTIALS = "invalid-credentials"
    INVALID_REFRESH = "invalid-refresh"
    USER_EXISTS = "user-exists"
    NOT_FOUND = "not-found"
    UNAUTHORIZED = "unauthorized"
    INVALID_OLD_PASSWORD = "invalid-old-password"
    NEW_PASSWORD_EQUALS_OLD = "new-password-equals-old"
    OTP_IS_INCORRECT = "otp-is-incorrect"
    OTP_IS_EXPIRED = "otp-is-expired"
    TOO_MANY_ATTEMPTS = "too-many-attempts"
    EMAIL_IS_UNVERIFIED = "email-unverified"
    VALIDATION_ERROR = "validation-error"
    UNSUPPORTED_MEDIA_TYPE = "unsupported-media-type"
    FILE_TOO_LARGE = "file-too-large"
    FILE_NOT_FOUND = "file-not-found"
    FILE_ACCESS_DENIED = "file-access-denied"

class ApiException(Exception):
    """Base Exception Class for the application"""
    status_code: int = 500
    type: ApiExceptionType
    message: str

    def __init__(self, message: str | None = None, body: object | None = None):
        self.message = message or self.message
        self.body = body
        super().__init__(self.message)
    
    def to_content(self) -> dict:
        content = {
         "message": self.message,
         "type": self.type,
        }
        if self.body is not None:
            content["body"] = self.body
        return content
    
    def __str__(self) -> str:
        base = f"{type(self).__name__}[{self.status_code} {self.type.value}]: {self.message}"
        if self.body is not None:
            base += f" | body={self.body!r}"
        return base

    def __repr__(self) -> str:
        return f"{type(self).__name__}(message={self.message!r}, body={self.body!r})"

class InternalServerError(ApiException):
    status_code = 500
    type = ApiExceptionType.INTERNAL_ERROR
    message = "Internal server error"

class InvalidCredentialsError(ApiException):
    status_code = 401
    type = ApiExceptionType.INVALID_CREDENTIALS
    message = "Incorrect email or password"

class InvalidRefreshError(ApiException):
    status_code = 401
    type = ApiExceptionType.INVALID_REFRESH
    message = "Invalid Refresh Token"

class UserAlreadyExistsError(ApiException):
    status_code = 409
    type = ApiExceptionType.USER_EXISTS
    message = "User with this email already exists"

class UnauthorizedError(ApiException):
    status_code = 401
    type = ApiExceptionType.UNAUTHORIZED
    message = "Could not validate credentials"

class UserNotFoundError(ApiException):
    status_code = 404
    type = ApiExceptionType.NOT_FOUND
    message = "User not found"

class InvalidOldPasswordError(ApiException):
    status_code = 400
    type = ApiExceptionType.INVALID_OLD_PASSWORD
    message = "Incorrect old password"

class NewPasswordEqualsOldError(ApiException):
    status_code = 400
    type = ApiExceptionType.NEW_PASSWORD_EQUALS_OLD
    message = "New password equals old"

class OtpIsExpiredError(ApiException):
    status_code = 400
    type = ApiExceptionType.OTP_IS_EXPIRED
    message = "Otp is expired"

class OtpIsIncorrectError(ApiException):
    status_code = 400
    type = ApiExceptionType.OTP_IS_INCORRECT
    message = "Otp is incorrect"

class TooManyAttemptsError(ApiException):
    status_code = 429
    type = ApiExceptionType.TOO_MANY_ATTEMPTS
    message = "Too many attempts, try again later"

class EmailIsUnverifiedError(ApiException):
    status_code = 403
    type = ApiExceptionType.EMAIL_IS_UNVERIFIED
    message = "Email is not verified"

class UnsupportedMediaTypeError(ApiException):
    status_code = 415
    type = ApiExceptionType.UNSUPPORTED_MEDIA_TYPE
    message = "Unsupported file type"

class FileTooLargeError(ApiException):
    status_code = 413
    type = ApiExceptionType.FILE_TOO_LARGE
    message = "File is too large"

class FileMissingError(ApiException):
    status_code = 404
    type = ApiExceptionType.FILE_NOT_FOUND
    message = "File not found"

class FileAccessDeniedError(ApiException):
    status_code = 403
    type = ApiExceptionType.FILE_ACCESS_DENIED
    message = "Access to this file is denied"


class ErrorResponse(BaseModel):
    """Unified error shape for the client. `type` is a machine-readable code (switch
    on it, not on message). `body` is optional details (e.g. the field list for 422)."""

    message: str
    type: ApiExceptionType
    body: object | None = None


def error_responses(*status_codes: int) -> dict[int, dict]:
    """Helper for the `responses=` route param: documents in OpenAPI/Swagger that
    these statuses return an ErrorResponse. Example: responses=error_responses(401, 404)."""
    return {code: {"model": ErrorResponse} for code in status_codes}
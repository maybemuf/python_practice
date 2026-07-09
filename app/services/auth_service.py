"""Authentication business logic.

Routers (app/routers/auth.py) stay thin: they take the HTTP input and delegate
here. This module holds the rules, transactions and domain exceptions; there is
no FastAPI or HTTP here. That lets the logic be tested without TestClient and
reused outside of HTTP.
"""
import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash
from sqlmodel import Session, select

from app.dependencies import logger
from app.models.change_password import ChangePasswordBody, ResetPasswordBody
from app.models.exceptions import (
    InvalidCredentialsError,
    InvalidOldPasswordError,
    InvalidRefreshError,
    NewPasswordEqualsOldError,
    OtpIsExpiredError,
    OtpIsIncorrectError,
    TooManyAttemptsError,
    UserAlreadyExistsError,
)
from app.models.otp import MAX_OTP_ATTEMPTS, OtpRawCodeStr, OTPRequest, OTPType
from app.models.refresh_token import RefreshToken
from app.models.user import AuthResponse, User, UserCreate
from app.settings import settings
from app.utils import ensure_utc

password_hash = PasswordHash.recommended()


# ---------------------------------------------------------------------------
# Token / crypto helpers
# ---------------------------------------------------------------------------


def create_access_token(user_id: uuid.UUID) -> str:
    to_encode = {
        "sub": str(user_id),
        "exp": datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def create_db_refresh_token(refresh_token: str, user_id: uuid.UUID) -> RefreshToken:
    return RefreshToken(
        user_id=user_id,
        token_hash=hash_refresh_token(refresh_token),
        expires_at=datetime.now(UTC) + timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES),
    )


# ---------------------------------------------------------------------------
# DB / domain helpers
# ---------------------------------------------------------------------------


def get_user_with_email(session: Session, email: str) -> User | None:
    return session.exec(select(User).where(User.email == email)).first()


def revoke_all_refresh_tokens(session: Session, user_id: uuid.UUID) -> None:
    now = datetime.now(UTC)
    statement = select(RefreshToken).where(
        RefreshToken.user_id == user_id,
        RefreshToken.revoked_at.is_(None),
    )
    for token in session.exec(statement):
        token.revoked_at = now
        session.add(token)


def invalidate_previous_otp_requests(
    session: Session, otp_type: OTPType, user_id: uuid.UUID
) -> None:
    statement = select(OTPRequest).where(
        OTPRequest.otp_type == otp_type,
        OTPRequest.user_id == user_id,
        OTPRequest.consumed_at.is_(None),
    )
    now = datetime.now(UTC)
    for request in session.exec(statement).all():
        request.invalidated_at = now


def create_otp_request(otp_type: OTPType, user_id: uuid.UUID) -> tuple[str, OTPRequest]:
    raw_code = f"{secrets.randbelow(1_000_000):06d}"
    otp_request = OTPRequest.issue(raw_code, user_id, otp_type)
    return raw_code, otp_request


def verify_otp_request(
    session: Session, user_id: uuid.UUID, otp_type: OTPType, raw_code: OtpRawCodeStr
) -> None:
    now = datetime.now(UTC)
    statement = select(OTPRequest).where(
        OTPRequest.user_id == user_id,
        OTPRequest.otp_type == otp_type,
        OTPRequest.consumed_at.is_(None),
        OTPRequest.invalidated_at.is_(None),
    )
    otp_request = session.exec(statement).first()
    if otp_request is None:
        raise OtpIsIncorrectError()
    if otp_request.is_expired():
        raise OtpIsExpiredError()
    if otp_request.attempts >= MAX_OTP_ATTEMPTS:
        # Limit reached — kill the code and block further attempts (anti-bruteforce).
        otp_request.invalidated_at = now
        session.add(otp_request)
        session.commit()
        raise TooManyAttemptsError()
    if not otp_request.verify(raw_code):
        # Persist the failed attempt BEFORE raising: otherwise the route never
        # reaches commit and the counter is rolled back together with the session.
        otp_request.attempts += 1
        session.add(otp_request)
        session.commit()
        raise OtpIsIncorrectError()

    otp_request.consumed_at = now


def authenticate_user(session: Session, email: str, password: str) -> User | None:
    user = get_user_with_email(session, email)
    if not user:
        return None
    if not password_hash.verify(password, user.password_hash):
        return None
    return user


def _issue_auth_response(session: Session, user: User) -> AuthResponse:
    """Issues a fresh token pair for the user and returns an AuthResponse. Called
    after all user changes are already in the session; it does commit + refresh."""
    refresh_token = generate_refresh_token()
    session.add(create_db_refresh_token(refresh_token, user.id))
    session.commit()
    session.refresh(user)
    access_token = create_access_token(user.id)
    return AuthResponse(access_token=access_token, refresh_token=refresh_token, user=user)


# ---------------------------------------------------------------------------
# High-level operations (used by the router)
# ---------------------------------------------------------------------------


def register(session: Session, body: UserCreate) -> AuthResponse:
    if get_user_with_email(session, email=body.email) is not None:
        raise UserAlreadyExistsError()
    hashed_pass = password_hash.hash(body.password)
    user = User.model_validate(body, update={"password_hash": hashed_pass})
    session.add(user)
    session.flush()  # ensure the user row exists before inserting the FK-dependent token
    return _issue_auth_response(session, user)


def login(session: Session, email: str, password: str) -> AuthResponse:
    user = authenticate_user(session, email, password)
    if not user:
        raise InvalidCredentialsError()
    return _issue_auth_response(session, user)


def rotate_refresh(session: Session, refresh_token: str) -> AuthResponse:
    hashed = hash_refresh_token(refresh_token)
    token = session.exec(
        select(RefreshToken).where(RefreshToken.token_hash == hashed)
    ).first()

    if token is None:
        raise InvalidRefreshError()
    if token.revoked_at is not None:
        # Reuse of a revoked token → likely theft: revoke all of the user's tokens.
        revoke_all_refresh_tokens(session, token.user_id)
        session.commit()
        raise InvalidRefreshError()
    if ensure_utc(token.expires_at) < datetime.now(UTC):
        raise InvalidRefreshError()

    token.revoked_at = datetime.now(UTC)
    session.add(token)
    user = session.get(User, token.user_id)
    return _issue_auth_response(session, user)


def change_password(session: Session, user: User, body: ChangePasswordBody) -> AuthResponse:
    if not password_hash.verify(body.old_password, user.password_hash):
        raise InvalidOldPasswordError()
    if password_hash.verify(body.new_password, user.password_hash):
        raise NewPasswordEqualsOldError()
    user.password_hash = password_hash.hash(body.new_password)
    revoke_all_refresh_tokens(session, user.id)
    session.add(user)
    return _issue_auth_response(session, user)


def request_reset_password(session: Session, email: str) -> None:
    """Anti-enumeration: return silently if the user doesn't exist. The route always returns 200."""
    user = get_user_with_email(session, email)
    if user is None:
        return
    invalidate_previous_otp_requests(session, otp_type=OTPType.PASSWORD_RECOVERY, user_id=user.id)
    raw_code, otp_request = create_otp_request(
        otp_type=OTPType.PASSWORD_RECOVERY, user_id=user.id
    )
    session.add(otp_request)
    session.commit()
    # TODO: send the code via an email provider; for now just log it.
    logger.debug(f"User({user.id}) wants to change password\nOTPCode: {raw_code}")


def reset_password(session: Session, body: ResetPasswordBody) -> AuthResponse:
    # A successful reset also verifies the email (if not verified yet).
    user = get_user_with_email(session, body.email)
    if user is None:
        # No enumeration: a non-existent email → the same error as a wrong code.
        raise OtpIsIncorrectError()

    verify_otp_request(session, user.id, otp_type=OTPType.PASSWORD_RECOVERY, raw_code=body.raw_code)

    user.password_hash = password_hash.hash(body.new_password)
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC)
    revoke_all_refresh_tokens(session, user.id)
    session.add(user)
    return _issue_auth_response(session, user)


def request_verify_email(session: Session, user: User) -> None:
    invalidate_previous_otp_requests(
        session, otp_type=OTPType.EMAIL_VERIFICATION, user_id=user.id
    )
    raw_code, otp_request = create_otp_request(
        otp_type=OTPType.EMAIL_VERIFICATION, user_id=user.id
    )
    session.add(otp_request)
    session.commit()
    # TODO: send the code via an email provider; for now just log it.
    logger.debug(f"User({user.id}) wants to verify their email\nOTPCode: {raw_code}")


def verify_email(session: Session, user: User, code: OtpRawCodeStr) -> User:
    verify_otp_request(session, user.id, otp_type=OTPType.EMAIL_VERIFICATION, raw_code=code)
    user.email_verified_at = datetime.now(UTC)
    session.commit()
    session.refresh(user)
    return user

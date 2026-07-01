import secrets
from typing import Annotated
import uuid
import hashlib
from fastapi import APIRouter, Body, Depends
from datetime import datetime, timedelta, timezone
from fastapi.security import OAuth2PasswordRequestForm
from pwdlib import PasswordHash
from pydantic.networks import EmailStr
from sqlmodel import select
from app.dependencies import SessionDep
from app.dependencies import logger
from app.dependencies.user import UserDep
from app.models import UserPublic
from app.models.change_password import ChangePasswordBody, ResetPasswordBody
from app.models.exceptions import InvalidCredentialsError, InvalidOldPasswordError, InvalidRefreshError, NewPasswordEqualsOldError, OtpIsExpiredError, OtpIsIncorrectError, UserAlreadyExistsError, UserNotFoundError
from app.models.otp import OTPRequest, OTPType, OtpRawCodeStr
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserCreate, AuthResponse
from app.settings import settings
from app.utils import ensure_utc
import jwt

password_hash = PasswordHash.recommended()

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)

def create_access_token(user_id: uuid.UUID):
    to_encode = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(minutes = settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm = settings.JWT_ALGORITHM)

def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def generate_refresh_token() -> str:
    return secrets.token_urlsafe(32)

def create_db_refresh_token(refresh_token: str, user_id: uuid.UUID) -> RefreshToken:
    token_hashed = hash_refresh_token(refresh_token)
    return RefreshToken(
        user_id=user_id,
        token_hash=token_hashed,
        expires_at= datetime.now(timezone.utc) + timedelta(minutes = settings.REFRESH_TOKEN_EXPIRE_MINUTES)
    )

def revoke_all_refresh_tokens(session: SessionDep, user_id: uuid.UUID):
    now = datetime.now(timezone.utc)
    all_tokens_statement = select(RefreshToken).where(RefreshToken.user_id == user_id,  RefreshToken.revoked_at.is_(None))
    tokens = session.exec(all_tokens_statement)
    for token_to_revoke in tokens:
        token_to_revoke.revoked_at = now
        session.add(token_to_revoke)

def get_user_with_email(session: SessionDep, email: str) -> User | None:
    return session.exec(select(User).where(User.email == email)).first()

def invalidate_previous_otp_requests(session: SessionDep, otp_type: OTPType, user_id: uuid.UUID):
    statement = select(OTPRequest).where(
        OTPRequest.otp_type == otp_type,
        OTPRequest.user_id == user_id,
        OTPRequest.consumed_at.is_(None),
    )
    otp_requests_to_invalidate = session.exec(statement).all()
    now = datetime.now(timezone.utc)
    for request in otp_requests_to_invalidate:
        request.invalidated_at = now

def create_otp_request(otp_type: OTPType, user_id: uuid.UUID) -> tuple[str, OTPRequest]:
    raw_code = f"{secrets.randbelow(1_000_000):06d}"
    otp_request = OTPRequest.issue(raw_code, user_id, otp_type)
    return raw_code, otp_request

def verify_otp_request(session: SessionDep, user_id: uuid.UUID, otp_type: OTPType, raw_code: OtpRawCodeStr) -> None:
    now = datetime.now(timezone.utc)
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
    if not otp_request.verify(raw_code):
        raise OtpIsIncorrectError()

    otp_request.consumed_at = now

def authenticate_user(session: SessionDep, email: str, password: str):
    user = get_user_with_email(session, email)
    if not user:
        return None
    if not password_hash.verify(password, user.password_hash):
        return None
    return user

@router.post("/register")
def register_user(body: UserCreate, session: SessionDep) -> AuthResponse:
    existing = get_user_with_email(session, email=body.email)
    if existing is not None:
        raise UserAlreadyExistsError()
    hashed_pass = password_hash.hash(body.password)
    db_user = User.model_validate(body, update={"password_hash": hashed_pass})
    session.add(db_user)
    session.flush()  # гарантуємо, що рядок user існує до вставки FK-залежного токена
    refresh_token = generate_refresh_token()
    db_refresh_token = create_db_refresh_token(refresh_token, db_user.id)
    session.add(db_refresh_token)
    session.commit()
    token = create_access_token(db_user.id)
    return AuthResponse(access_token=token, refresh_token=refresh_token, user=db_user)

@router.post("/login")
def login_user(form_data: Annotated[OAuth2PasswordRequestForm, Depends()], session: SessionDep) -> AuthResponse:
    user = authenticate_user(session, form_data.username, form_data.password)
    if not user:
        raise InvalidCredentialsError()
    refresh_token = generate_refresh_token()
    db_refresh_token = create_db_refresh_token(refresh_token, user.id)
    session.add(db_refresh_token)
    session.commit()
    token = create_access_token(user.id)
    return AuthResponse(access_token=token, refresh_token=refresh_token, user=user)

@router.post("/refresh")
def rotate_refresh_token(refresh_token: Annotated[str, Body(embed=True)], session: SessionDep) -> AuthResponse:
    hashed = hash_refresh_token(refresh_token)
    statement = select(RefreshToken).where(RefreshToken.token_hash == hashed)
    token = session.exec(statement).first()
    
    if token is None:
        raise InvalidRefreshError()
    elif token.revoked_at is not None:
        revoke_all_refresh_tokens(session, token.user_id)
        session.commit()
        raise InvalidRefreshError()
    elif ensure_utc(token.expires_at) < datetime.now(timezone.utc):
        raise InvalidRefreshError()

    token.revoked_at = datetime.now(timezone.utc)
    new_refresh = generate_refresh_token()
    new_db_refresh_token = create_db_refresh_token(new_refresh, token.user_id)
    session.add(token)
    session.add(new_db_refresh_token)
    session.commit()

    access_token = create_access_token(token.user_id)
    user = session.get(User, token.user_id)
    
    return AuthResponse(access_token=access_token, refresh_token=new_refresh, user=user)

@router.post("/change-password")
def change_user_password(body: ChangePasswordBody, session: SessionDep, current_user: UserDep) -> AuthResponse:
    user = current_user
    if not password_hash.verify(body.old_password, user.password_hash):
        raise InvalidOldPasswordError()
    elif password_hash.verify(body.new_password, user.password_hash):
        raise NewPasswordEqualsOldError()
    user.password_hash = password_hash.hash(body.new_password)
    revoke_all_refresh_tokens(session, user.id)
    refresh_token = generate_refresh_token()
    db_refresh_token = create_db_refresh_token(refresh_token, user.id)
    access_token = create_access_token(user.id)
    session.add(db_refresh_token)
    session.add(user)
    session.commit()
    session.refresh(user)

    return AuthResponse(access_token=access_token, refresh_token=refresh_token, user=user)

@router.post("/request-reset-password")
def request_reset_user_password(email: Annotated[EmailStr, Body(embed=True)], session: SessionDep):
    user = get_user_with_email(session, email)
    if user is not None:
        invalidate_previous_otp_requests(session, otp_type=OTPType.PASSWORD_RECOVERY, user_id=user.id)
        raw_code, otp_request = create_otp_request(otp_type=OTPType.PASSWORD_RECOVERY, user_id=user.id)
        session.add(otp_request)
        session.commit()
        logger.debug(f"User({user.id}) wants to change password\nOTPCode: {raw_code}")
    return {"message": "If an account with that email exists, a reset code has been sent."}

@router.post("/reset-password")
def reset_user_password(body: ResetPasswordBody, session: SessionDep) -> AuthResponse:
    # automaticaly verifes user email if not verifed upon successful password reset
    user = get_user_with_email(session, body.email)
    if user is None:
        raise OtpIsIncorrectError()

    verify_otp_request(session, user.id, otp_type=OTPType.PASSWORD_RECOVERY, raw_code=body.raw_code)
    
    new_password_hashed = password_hash.hash(body.new_password)
    user.password_hash = new_password_hashed
    revoke_all_refresh_tokens(session, user.id)
    refresh_token = generate_refresh_token()
    db_refresh_token = create_db_refresh_token(refresh_token, user.id)
    access_token = create_access_token(user.id)
    if (user.email_verified_at is None):
        user.email_verified_at = datetime.now(timezone.utc)
    session.add(db_refresh_token)
    session.add(user)
    session.commit()
    session.refresh(user)

    return AuthResponse(access_token=access_token, refresh_token=refresh_token, user=user)
    
@router.post("/request-verify-email")
def send_verify_email_otp(session: SessionDep, user: UserDep):
    invalidate_previous_otp_requests(session, otp_type=OTPType.EMAIL_VERIFICATION, user_id=user.id)
    raw_code, otp_request = create_otp_request(otp_type=OTPType.EMAIL_VERIFICATION, user_id=user.id)
    session.add(otp_request)
    session.commit()
    logger.debug(f"User({user.id}) wants to verify their email\nOTPCode: {raw_code}")

@router.post("/verify-email")
def verify_user_email(code: Annotated[OtpRawCodeStr, Body(embed=True)], session: SessionDep, user: UserDep) -> UserPublic:
    verify_otp_request(session, user.id, otp_type=OTPType.EMAIL_VERIFICATION, raw_code=code)

    user.email_verified_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(user)
    
    return user
    
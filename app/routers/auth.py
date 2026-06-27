import secrets
from typing import Annotated
import uuid
import hashlib
from fastapi import APIRouter, Body, Depends
from datetime import datetime, timedelta, timezone
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pwdlib import PasswordHash
from sqlmodel import select
from app.dependencies import SessionDep
from app.models.exceptions import InvalidCredentialsError, InvalidRefreshError, UserAlreadyExistsError
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserCreate, AuthResponse
from app.settings import settings
import jwt

password_hash = PasswordHash.recommended()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

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

def get_user_with_email(session: SessionDep, email: str) -> User | None:
    return session.exec(select(User).where(User.email == email)).first()

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
    refresh_token = generate_refresh_token()
    db_refresh_token = create_db_refresh_token(refresh_token, db_user.id)
    session.add(db_user)
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
def refresh_token(refresh_token: Annotated[str, Body(embed=True)], session: SessionDep) -> AuthResponse:
    hashed = hash_refresh_token(refresh_token)
    statement = select(RefreshToken).where(RefreshToken.token_hash == hashed)
    token = session.exec(statement).first()
    
    if token is None:
        raise InvalidRefreshError()
    elif token.revoked_at is not None:
        all_tokens_statement = select(RefreshToken).where(RefreshToken.user_id == token.user_id)
        tokens = session.exec(all_tokens_statement)
        for token_to_revoke in tokens:
            token_to_revoke.revoked_at = datetime.now(timezone.utc)
            session.add(token_to_revoke)
        session.commit()
        raise InvalidRefreshError()
    else:
        # SQLite не зберігає tzinfo — при зчитуванні expires_at приходить naive.
        # Значення вже в UTC, тож просто домальовуємо ярлик без зсуву часу.
        expires_at = token.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
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


from typing import Annotated
from fastapi import APIRouter, Depends
from datetime import datetime, timedelta, timezone
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pwdlib import PasswordHash
from sqlmodel import select
from app.dependencies import SessionDep
from app.models.exceptions import InvalidCredentialsError, UserAlreadyExistsError
from app.models.user import User, UserCreate, AuthResponse
from app.settings import settings
import jwt

password_hash = PasswordHash.recommended()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)

def create_access_token(user_id: int):
    to_encode = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(minutes = settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm = settings.JWT_ALGORITHM)

def get_user_with_email(session: SessionDep, email: str) -> User | None:
    return session.exec(select(User).where(User.email == email)).first()

def authenticate_user(session:SessionDep, email: str, password: str):
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
    session.commit()
    session.refresh(db_user)
    token = create_access_token(db_user.id)
    return AuthResponse(access_token=token, user=db_user)

@router.post("/login")
def login_user(form_data: Annotated[OAuth2PasswordRequestForm, Depends()], session: SessionDep) -> AuthResponse:
    user = authenticate_user(session, form_data.username, form_data.password)
    if not user:
        raise InvalidCredentialsError()
    token = create_access_token(user.id)
    return AuthResponse(access_token=token, user=user)
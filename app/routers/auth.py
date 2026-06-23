from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timedelta, timezone
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pwdlib import PasswordHash
from sqlmodel import select
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_409_CONFLICT
from app.dependencies import SessionDep
from app.models.user import User, UserCreate, AuthResponse, UserPublic
import jwt

SECRET_KEY="2d788292a211e87247fbe424e0cab534c0558752396d3c8910cc5bd1c116b3ee"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

password_hash = PasswordHash.recommended()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)

def create_access_token(user_id: int):
    to_encode = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
    }
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
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
        raise HTTPException(status_code=HTTP_409_CONFLICT, detail="User with this email already exists")
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
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    token = create_access_token(user.id)
    return AuthResponse(access_token=token, user=user)
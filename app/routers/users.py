import jwt
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from starlette.status import HTTP_401_UNAUTHORIZED
from app import settings
from app.dependencies import SessionDep
from app.models.user import User, UserPublic
from app.routers.auth import oauth2_scheme
from app.settings import settings


router = APIRouter(
    prefix="/users",
    tags=["users"]
)

def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: SessionDep,
) -> User:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except jwt.PyJWTError:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = session.get(User, int(user_id))
    if user is None:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="User not found")
    return user

@router.get("/me", response_model=UserPublic)
def read_me(current_user: Annotated[User, Depends(get_current_user)]):
    return current_user
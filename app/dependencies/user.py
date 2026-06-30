from typing import Annotated
from uuid import UUID

from fastapi import Depends
import jwt

from app.settings import settings
from app.dependencies.auth import oauth2_scheme
from app.dependencies.session import SessionDep
from app.models import User
from app.models.exceptions import EmailIsUnverifiedError, UnauthorizedError, UserNotFoundError


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: SessionDep,
) -> User:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise UnauthorizedError()
        user_uuid = UUID(user_id)
    except (jwt.PyJWTError, ValueError, TypeError):
        raise UnauthorizedError()
    user = session.get(User, user_uuid)
    if user is None:
        raise UserNotFoundError()
    return user

UserDep = Annotated[User, Depends(get_current_user)]

def check_user_verified(user: UserDep) -> User:
    if user.email_verified_at is None:
        raise EmailIsUnverifiedError()
    return user

VerifiedUserDep = Annotated[User, Depends(check_user_verified)]
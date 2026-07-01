from fastapi import APIRouter

from app.dependencies.user import UserDep
from app.models.exceptions import error_responses
from app.models.user import UserPublic

router = APIRouter(
    prefix="/users",
    tags=["users"],
)

@router.get("/me", response_model=UserPublic, responses=error_responses(401))
def read_me(current_user: UserDep):
    """Returns the profile of the current authenticated user."""
    return current_user
from fastapi import APIRouter
from app.dependencies.user import UserDep
from app.models.user import UserPublic

router = APIRouter(
    prefix="/users",
    tags=["users"]
)

@router.get("/me", response_model=UserPublic)
def read_me(current_user: UserDep):
    return current_user
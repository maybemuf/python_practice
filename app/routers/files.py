from fastapi import APIRouter, UploadFile

from app.dependencies.user import VerifiedUserDep

router = APIRouter(
    prefix = "/files",
    tags = ["files"],
)

@router.post()
def upload_file(file: UploadFile, user: VerifiedUserDep):
    pass
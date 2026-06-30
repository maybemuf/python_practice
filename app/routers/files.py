from typing import Annotated
from urllib.parse import quote
import uuid

from fastapi.responses import JSONResponse, StreamingResponse
import magic
from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.orm import state
from sqlmodel import select
from starlette.status import HTTP_204_NO_CONTENT

from app.dependencies import SessionDep
from app.dependencies.user import VerifiedUserDep
from app.models.exceptions import FileMissingError, UnsupportedMediaTypeError
from app.models.file import FileObject, FilePublic, FileStatus
from app.models.pagination import PaginationQuerry
from app.services.storage import storage
from app.services.storage.metered import MeteredReader
from app.settings import settings

mime = magic.Magic(mime=True)

ALLOWED_CONTENT_TYPES: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "application/pdf": "pdf",
    "text/plain": "txt",
    "text/csv": "csv",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-powerpoint": "ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
}

def get_user_file_obj(file_id: uuid.UUID, session: SessionDep, user: VerifiedUserDep) -> FileObject:
    file_obj = session.get(FileObject, file_id)
    if file_obj is None or file_obj.owner_id != user.id:
        raise FileMissingError()
    return file_obj

UserFileObjDep = Annotated[FileObject, Depends(get_user_file_obj)]

router = APIRouter(
    prefix="/files",
    tags=["files"],
)

@router.post("", response_model=FilePublic)
async def upload_file(
    file: UploadFile,
    user: VerifiedUserDep,
    session: SessionDep,
) -> FileObject:
    header = await file.read(2048)
    content_type = mime.from_buffer(header)
    await file.seek(0)

    if content_type not in ALLOWED_CONTENT_TYPES:
        raise UnsupportedMediaTypeError()

    file_id = uuid.uuid4()
    ext = ALLOWED_CONTENT_TYPES[content_type]
    key = f"users/{user.id}/{file_id}.{ext}"

    reader = MeteredReader(file, settings.MAX_UPLOAD_SIZE)
    try:
        await storage.save(key, reader, content_type)
    except Exception:
        await storage.delete(key)
        raise

    file_obj = FileObject(
        id=file_id,
        owner_id=user.id,
        storage_key=key,
        original_filename=file.filename or "",
        content_type=content_type,
        size_bytes=reader.size,
        checksum=reader.checksum,
        status=FileStatus.SAVED,
    )
    session.add(file_obj)
    session.commit()
    session.refresh(file_obj)
    return file_obj

@router.get('/{file_id}', response_class=StreamingResponse)
async def download_file(file: UserFileObjDep) -> StreamingResponse:
    filename = quote(file.original_filename or str(file.id))
    if not await storage.exists(file.storage_key):
        raise FileMissingError()
    return StreamingResponse(
        storage.open_stream(file.storage_key),
        media_type=file.content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
            "Content-Length": str(file.size_bytes),
        }
    )
    
@router.delete('/{file_id}', status_code=HTTP_204_NO_CONTENT)
async def delete_file(file: UserFileObjDep, session: SessionDep) -> None:
    session.delete(file)
    session.commit()
    await storage.delete(file.storage_key)

@router.get('', response_model=list[FilePublic])
def get_user_file_objects(pagination: PaginationQuerry, user: VerifiedUserDep, session: SessionDep) -> list[FileObject]:
    statement = select(FileObject).where(FileObject.owner_id == user.id).offset(pagination.offset).limit(pagination.limit)
    file_objects = session.exec(statement).all()
    return file_objects

@router.get('/{file_id}/metadata', response_model=FilePublic)
def get_user_file_metadata(file: UserFileObjDep) -> FileObject:
    return file
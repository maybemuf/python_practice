import uuid
from typing import Annotated
from urllib.parse import quote

import magic
from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import StreamingResponse
from sqlmodel import select
from starlette.status import HTTP_204_NO_CONTENT

from app.dependencies import SessionDep
from app.dependencies.user import VerifiedUserDep
from app.models.exceptions import (
    FileMissingError,
    UnsupportedMediaTypeError,
    error_responses,
)
from app.models.file import FileObject, FilePublic, FileStatus
from app.models.pagination import PaginationQuery
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

@router.post("", response_model=FilePublic, responses=error_responses(401, 403, 413, 415))
async def upload_file(
    file: UploadFile,
    user: VerifiedUserDep,
    session: SessionDep,
) -> FileObject:
    """Uploads a file. The type is detected from magic bytes (not the client's
    Content-Type); the size is capped by MAX_UPLOAD_SIZE (413 when exceeded)."""
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

@router.get(
    '/{file_id}',
    response_class=StreamingResponse,
    responses=error_responses(401, 403, 404),
)
async def download_file(file: UserFileObjDep) -> StreamingResponse:
    """Streams the file's content. Owner only; someone else's/nonexistent → 404."""
    if not await storage.exists(file.storage_key):
        raise FileMissingError()
    # Derive the ASCII-safe fallback name from the ext in storage_key
    # ("users/<id>/<uuid>.<ext>"); the full UTF-8 name goes via filename* (RFC 5987).
    ext = file.storage_key.rsplit(".", 1)[-1]
    utf8_name = quote(file.original_filename or f"{file.id}.{ext}")
    return StreamingResponse(
        storage.open_stream(file.storage_key),
        media_type=file.content_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{file.id}.{ext}"; '
                f"filename*=UTF-8''{utf8_name}"
            ),
            "Content-Length": str(file.size_bytes),
        }
    )
    
@router.delete(
    '/{file_id}',
    status_code=HTTP_204_NO_CONTENT,
    responses=error_responses(401, 403, 404),
)
async def delete_file(file: UserFileObjDep, session: SessionDep) -> None:
    """Deletes the file (DB row + bytes in storage). Owner only."""
    session.delete(file)
    session.commit()
    await storage.delete(file.storage_key)

@router.get('', response_model=list[FilePublic], responses=error_responses(401, 403))
def get_user_file_objects(
    pagination: PaginationQuery,
    user: VerifiedUserDep,
    session: SessionDep,
) -> list[FileObject]:
    """List of the current user's files with pagination (limit/offset)."""
    statement = (
        select(FileObject)
        .where(FileObject.owner_id == user.id)
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    file_objects = session.exec(statement).all()
    return file_objects

@router.get(
    '/{file_id}/metadata',
    response_model=FilePublic,
    responses=error_responses(401, 403, 404),
)
def get_user_file_metadata(file: UserFileObjDep) -> FileObject:
    """File metadata without downloading the content. Owner only."""
    return file
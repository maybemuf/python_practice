import uuid

import magic
from fastapi import APIRouter, UploadFile

from app.dependencies import SessionDep
from app.dependencies.user import VerifiedUserDep
from app.models.exceptions import UnsupportedMediaTypeError
from app.models.file import FileObject, FilePublic, FileStatus
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

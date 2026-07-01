from collections.abc import AsyncIterator
from pathlib import Path

import aiofiles
import aiofiles.os

from app.models.exceptions import FileMissingError


class LocalStorage:
    def __init__(self, base_dir: str):
        self.base = Path(base_dir)

    def _path(self, key: str) -> Path:
        p = (self.base / key).resolve()
        if not p.is_relative_to(self.base.resolve()):
            raise ValueError("Invalid storage key")
        return p
    
    async def save(self, key: str, source, content_type: str) -> None:
        path = self._path(key)
        await aiofiles.os.makedirs(path.parent, exist_ok=True)
        async with aiofiles.open(path, "wb") as f:
            while chunk := await source.read(1024 * 1024):   # stream in 1 MB chunks
                await f.write(chunk)

    async def open_stream(self, key: str) -> AsyncIterator[bytes]:
        path = self._path(key)
        if not await aiofiles.os.path.exists(path):
            raise FileMissingError()
        async with aiofiles.open(path, "rb") as f:
            while chunk := await f.read(1024 * 1024):
                yield chunk

    async def exists(self, key: str) -> bool:
        path = self._path(key)
        return await aiofiles.os.path.exists(path)
    
    async def delete(self, key: str) -> None:
        path = self._path(key)
        if await aiofiles.os.path.exists(path):
            await aiofiles.os.remove(path)

    def url_for(self, key: str) -> str:
        return f"/files/{key}"
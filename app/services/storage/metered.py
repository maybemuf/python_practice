import hashlib
from typing import Protocol

from app.models.exceptions import FileTooLargeError


class AsyncReadable(Protocol):
    async def read(self, size: int = -1) -> bytes: ...


class MeteredReader:
    """Wraps an async file source, counting bytes and hashing them as they are
    read, and aborting once max_size is exceeded.

    Lets Storage.save() stay "dumb" (just writes chunks) while size, checksum and
    the size limit are computed once, in one place, for every storage backend.
    """

    def __init__(self, source: AsyncReadable, max_size: int):
        self._source = source
        self._max_size = max_size
        self._hasher = hashlib.sha256()
        self.size = 0

    async def read(self, size: int = -1) -> bytes:
        chunk = await self._source.read(size)
        if chunk:
            self.size += len(chunk)
            if self.size > self._max_size:
                raise FileTooLargeError()
            self._hasher.update(chunk)
        return chunk

    @property
    def checksum(self) -> str:
        return self._hasher.hexdigest()

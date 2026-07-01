"""Unit tests for storage and MeteredReader — no HTTP, no DB."""
import asyncio
import hashlib

import pytest

from app.models.exceptions import FileTooLargeError
from app.services.storage.local_storage import LocalStorage
from app.services.storage.metered import MeteredReader


class _AsyncBytes:
    """Minimal async source: yields the buffer in chunks of `size`."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    async def read(self, size: int = -1) -> bytes:
        if size < 0:
            chunk, self._pos = self._data[self._pos:], len(self._data)
            return chunk
        chunk = self._data[self._pos:self._pos + size]
        self._pos += len(chunk)
        return chunk


# --- MeteredReader -----------------------------------------------------------


def test_metered_reader_computes_size_and_checksum():
    data = b"hello world" * 100
    reader = MeteredReader(_AsyncBytes(data), max_size=10 * 1024)

    async def drain() -> bytes:
        buf = bytearray()
        while chunk := await reader.read(64):
            buf.extend(chunk)
        return bytes(buf)

    result = asyncio.run(drain())

    assert result == data
    assert reader.size == len(data)
    assert reader.checksum == hashlib.sha256(data).hexdigest()


def test_metered_reader_raises_when_over_limit():
    reader = MeteredReader(_AsyncBytes(b"x" * 100), max_size=10)

    async def drain() -> None:
        while await reader.read(64):
            pass

    with pytest.raises(FileTooLargeError):
        asyncio.run(drain())


# --- LocalStorage path traversal ---------------------------------------------


def test_local_storage_rejects_path_traversal(tmp_path):
    storage = LocalStorage(str(tmp_path))

    with pytest.raises(ValueError):
        storage._path("../../etc/passwd")


def test_local_storage_allows_valid_key(tmp_path):
    storage = LocalStorage(str(tmp_path))

    path = storage._path("users/abc/file.txt")

    assert str(path).startswith(str(tmp_path.resolve()))

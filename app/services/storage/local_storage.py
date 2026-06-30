from pathlib import Path
import aiofiles
import aiofiles.os

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
            while chunk := await source.read(1024 * 1024):   # стрімінг по 1 МБ
                await f.write(chunk)
    
    async def delete(self, key: str) -> None:
        path = self._path(key)
        if await aiofiles.os.path.exists(path):
            await aiofiles.os.remove(path)

    def url_for(self, key: str) -> str:
        return f"/files/{key}"
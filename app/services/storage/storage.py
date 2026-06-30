from typing import BinaryIO, Protocol

class Storage(Protocol):
    async def save(self, key: str, source: BinaryIO, content_type: str) -> None:
        """Saving the file"""

    async def delete(self, key: str) -> None:
        """Deleting the file"""
    
    def url_for(self, key: str) -> str:
        """Geting the url for the file"""

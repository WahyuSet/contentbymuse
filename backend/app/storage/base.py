from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class StoredObject:
    key: str
    size_bytes: int
    mime: str


class Storage(Protocol):
    async def put(self, key: str, data: bytes | Path, mime: str) -> StoredObject: ...
    def open(self, key: str) -> AsyncIterator[bytes]: ...
    async def local_path(self, key: str) -> Path: ...
    def public_url(self, key: str) -> str: ...
    async def delete(self, key: str) -> None: ...

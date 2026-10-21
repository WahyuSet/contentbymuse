from collections.abc import AsyncIterator
from pathlib import Path

from app.storage.base import StoredObject


class LocalStorage:
    def __init__(self, root: Path):
        self._root = Path(root).resolve()

    def _resolve(self, key: str) -> Path:
        path = (self._root / key).resolve()
        if path != self._root and self._root not in path.parents:
            raise ValueError(f"Kunci storage tidak valid: {key}")
        return path

    async def put(self, key: str, data: bytes | Path, mime: str) -> StoredObject:
        path = self._resolve(key)
        content = Path(data).read_bytes() if isinstance(data, Path) else data
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return StoredObject(key=key, size_bytes=len(content), mime=mime)

    async def open(self, key: str) -> AsyncIterator[bytes]:
        path = self._resolve(key)
        with path.open("rb") as fh:
            while chunk := fh.read(64 * 1024):
                yield chunk

    async def local_path(self, key: str) -> Path:
        return self._resolve(key)

    def public_url(self, key: str) -> str:
        self._resolve(key)
        return f"/api/files/{key}"

    async def delete(self, key: str) -> None:
        self._resolve(key).unlink(missing_ok=True)

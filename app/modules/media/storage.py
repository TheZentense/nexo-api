"""Los servicios usan claves; el adaptador decide dónde guardar los archivos."""

import shutil
from pathlib import Path
from typing import Protocol

from fastapi.responses import FileResponse, Response


class Storage(Protocol):
    def put(self, key: str, source: Path) -> None: ...
    def download(self, key: str, destination: Path) -> None: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...
    def response(self, key: str, content_type: str) -> Response: ...


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if path == self.root or not path.is_relative_to(self.root):
            raise ValueError("Invalid storage key")
        return path

    def put(self, key: str, source: Path) -> None:
        target = self.path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Las claves son únicas. Nunca reemplazamos un original existente.
        with target.open("xb") as output, source.open("rb") as stream:
            try:
                shutil.copyfileobj(stream, output)
            except Exception:
                output.close()
                target.unlink(missing_ok=True)
                raise

    def download(self, key: str, destination: Path) -> None:
        shutil.copyfile(self.path(key), destination)

    def exists(self, key: str) -> bool:
        return self.path(key).is_file()

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)

    def response(self, key: str, content_type: str) -> Response:
        return FileResponse(
            self.path(key),
            media_type=content_type,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

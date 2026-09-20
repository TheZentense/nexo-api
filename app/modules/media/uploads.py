from pathlib import Path

from fastapi import HTTPException, Request


async def receive_file(request: Request, destination: Path, *, limit: int, content_types: set[str]):
    header = request.headers.get("content-length")
    if header:
        try:
            size = int(header)
        except ValueError:
            raise HTTPException(400, "Invalid content length") from None
        if size < 0 or size > limit:
            raise HTTPException(413, "File exceeds the size limit")
    if request.headers.get("content-type", "").split(";")[0] not in content_types:
        raise HTTPException(415, "Unsupported content type")
    size = 0
    with destination.open("wb") as stream:
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                raise HTTPException(413, "File exceeds the size limit")
            stream.write(chunk)
    return size

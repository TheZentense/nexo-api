from starlette.datastructures import Headers
from starlette.responses import JSONResponse

PUBLIC_FORM_MAX_BYTES = 32 * 1024
PUBLIC_FORM_PATHS = {"/api/v1/contact-messages", "/api/v1/volunteer-applications"}


class PublicFormLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or scope["path"].rstrip("/") not in PUBLIC_FORM_PATHS
        ):
            await self.app(scope, receive, send)
            return

        length = Headers(scope=scope).get("content-length")
        if length is not None:
            try:
                size = int(length)
                if size < 0:
                    raise ValueError
            except ValueError:
                await self.reject(scope, receive, send, 400, "Invalid content length")
                return
            if size > PUBLIC_FORM_MAX_BYTES:
                await self.reject(scope, receive, send, 413, "Request body exceeds the size limit")
                return

        # Contamos los bytes recibidos aunque el cliente omita o falsee la cabecera.
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > PUBLIC_FORM_MAX_BYTES:
                await self.reject(scope, receive, send, 413, "Request body exceeds the size limit")
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        delivered = False

        async def limited_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, limited_receive, send)

    async def reject(self, scope, receive, send, status, detail):
        response = JSONResponse(
            {"detail": detail}, status_code=status, headers={"Cache-Control": "no-store"}
        )
        await response(scope, receive, send)

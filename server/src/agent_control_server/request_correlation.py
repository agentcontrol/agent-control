"""Preserve one parent request ID without copying authentication headers."""

from agent_control_models.request_context import request_id_context
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestCorrelationMiddleware:
    """Carry a bounded X-Request-ID through evaluation and return it to the caller."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        raw_id = headers.get(b"x-request-id", b"").decode("ascii", errors="replace")
        with request_id_context(raw_id or None) as request_id:

            async def send_with_request_id(message: Message) -> None:
                if message["type"] == "http.response.start":
                    message = dict(message)
                    message["headers"] = [
                        (key, value)
                        for key, value in message.get("headers", [])
                        if key.lower() != b"x-request-id"
                    ] + [(b"x-request-id", request_id.encode("ascii"))]
                await send(message)

            await self.app(scope, receive, send_with_request_id)

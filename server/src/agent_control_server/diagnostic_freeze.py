"""Reject configuration writes during the dedicated-stack diagnostic window."""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from . import diagnostic_lookup
from .diagnostic_metrics import _EVENTS


class DiagnosticFixtureFreeze:
    """Keep AC configuration fixed while the dedicated LT image is enabled.

    Reads, token exchange, evaluation and observation remain available. Freeze
    lasts until disabling the diagnostic or restoring the original image, even
    after cache expiry. Never enable this on a shared application.
    """

    def __init__(self, app: ASGIApp, *, api_base: str) -> None:
        self.app = app
        self._prefixes = tuple(
            api_base + "/" + name
            for name in ("agents", "controls", "control-bindings", "policies")
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            diagnostic_lookup.settings.enabled
            and scope["type"] == "http"
            and scope["method"] in {"POST", "PUT", "PATCH", "DELETE"}
            and any(
                scope["path"] == p or scope["path"].startswith(p + "/")
                for p in self._prefixes
            )
        ):
            _EVENTS.labels("on", "fixture_write_rejected").inc()
            response = JSONResponse(
                status_code=409,
                content={"detail": "Configuration is frozen for the controlled lookup diagnostic"},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)

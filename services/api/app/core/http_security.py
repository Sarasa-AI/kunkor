"""Contain HTTP failures and keep request credentials out of server access logs."""

import logging

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)


class PrivateAccessLogFilter(logging.Filter):
    """Uvicorn's request target can contain credentials, identifiers, and free text."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not isinstance(record.args, tuple) or len(record.args) != 5:
            # A changed format must not leak data or break Uvicorn's formatter.
            return False
        _, method, _, version, status = record.args
        safe_method = method if method in {
            "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "CONNECT", "TRACE"
        } else "OTHER"
        record.msg = '%s - "%s %s HTTP/%s" %s'
        record.args = ("[redacted]", safe_method, "[redacted]", version, status)
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


def install_private_access_logging() -> None:
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, PrivateAccessLogFilter) for item in access_logger.filters):
        access_logger.addFilter(PrivateAccessLogFilter())


class ContainHTTPFailures:
    """Catch the full ASGI response lifecycle, including streams and background tasks."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracked_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        except Exception as exc:
            logger.error("Request failed (%s)", type(exc).__name__)
            if not started:
                response = JSONResponse(
                    status_code=500, content={"detail": "Internal server error"}
                )
                await response(scope, receive, send)
            # Once headers are sent, do not fabricate success or replace the body.
            # Returning an incomplete stream makes Uvicorn close the connection
            # with a generic protocol error; the original exception never escapes.

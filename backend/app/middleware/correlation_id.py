"""
Correlation ID Middleware.

WHY THIS EXISTS:
────────────────
In a distributed system, one user action triggers multiple service calls.
Without a shared ID, you cannot connect logs across services.

Example without correlation ID:
  [INFO] Reservation attempt received
  [ERROR] DB write failed
  ← Which reservation caused this error? Impossible to know.

Example WITH correlation ID:
  [INFO] req_id=abc123 Reservation attempt received
  [ERROR] req_id=abc123 DB write failed
  ← Immediately obvious. One grep finds the full request journey.

Every request gets a UUID. If the client sends X-Request-ID header,
we use that (useful when the client wants to trace their own requests).
Otherwise we generate one. It flows through every log line.
"""

import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger()


class CorrelationIdMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next) -> Response:
        # Use client-provided ID or generate a new one
        correlation_id = request.headers.get("x-request-id", str(uuid.uuid4()))

        # Bind correlation ID to all logs in this request context
        structlog.contextvars.bind_contextvars(
            correlation_id=correlation_id,
            method=request.method,
            path=request.url.path,
        )

        # Process the request
        response = await call_next(request)

        # Return correlation ID in response headers so client can trace
        response.headers["x-request-id"] = correlation_id

        # Clean up context vars for this request
        structlog.contextvars.clear_contextvars()

        return response
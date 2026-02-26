"""Structured JSON request logging middleware for the FileGuard API.

:class:`RequestLoggingMiddleware` records every HTTP request as a structured
JSON log entry at ``INFO`` level, enriched with:

* A **correlation ID** — propagated from the incoming ``X-Correlation-ID``
  (or ``X-Request-ID``) header, or generated as a UUID v4 when absent.
* **Tenant context** — the tenant UUID extracted from ``request.state.tenant``
  (set by :class:`~fileguard.api.middleware.auth.AuthMiddleware`).  Logged as
  ``null`` for unauthenticated / public paths where no tenant is attached.
* Request metadata: HTTP method, URL path, response status code, and wall-clock
  duration in milliseconds.

The correlation ID is also:

* Stored on ``request.state.correlation_id`` so that downstream handlers and
  middleware (including :class:`~fileguard.services.audit.AuditService`) can
  include it in their own log entries without re-parsing headers.
* Echoed back to the client in the ``X-Correlation-ID`` response header to
  facilitate end-to-end tracing from client logs.

Middleware registration order
------------------------------
This middleware must be registered **after** (i.e. outside of)
:class:`~fileguard.api.middleware.auth.AuthMiddleware` so that it wraps the
full request–response lifecycle and can read ``request.state.tenant`` once
``AuthMiddleware`` has populated it::

    # Starlette processes middleware in reverse registration order.
    # add_middleware(X) then add_middleware(Y) → Y runs first.
    app.add_middleware(AuthMiddleware)
    app.add_middleware(RequestLoggingMiddleware)  # outermost — runs first

Log entry format
----------------
::

    {
      "event": "http_request",
      "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
      "tenant_id": "d290f1ee-6c54-4b01-90e6-d701748f0851",
      "method": "POST",
      "path": "/v1/scan",
      "status_code": 200,
      "duration_ms": 42.7
    }
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Headers checked (in priority order) for an incoming correlation ID.
_CORRELATION_HEADERS: tuple[str, ...] = ("x-correlation-id", "x-request-id")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Structured JSON per-request logging middleware.

    Logs every request as a single JSON object at ``INFO`` level after the
    response has been produced.  The log record includes a correlation ID,
    tenant context, HTTP metadata, and wall-clock duration.

    The correlation ID is:

    * Read from ``X-Correlation-ID`` or ``X-Request-ID`` request headers
      (first match wins).
    * Generated as a UUID v4 when no recognised header is present.
    * Written to ``request.state.correlation_id`` for downstream use.
    * Echoed in the ``X-Correlation-ID`` response header.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        correlation_id = self._extract_correlation_id(request)
        request.state.correlation_id = correlation_id

        start = time.monotonic()
        response = await call_next(request)
        duration_ms = round((time.monotonic() - start) * 1000, 2)

        tenant = getattr(request.state, "tenant", None)
        tenant_id: str | None = str(tenant.id) if tenant is not None else None

        log_entry = {
            "event": "http_request",
            "correlation_id": correlation_id,
            "tenant_id": tenant_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        }
        logger.info(json.dumps(log_entry))

        response.headers["X-Correlation-ID"] = correlation_id
        return response

    @staticmethod
    def _extract_correlation_id(request: Request) -> str:
        """Return a correlation ID for *request*.

        Checks ``X-Correlation-ID`` then ``X-Request-ID`` headers.  If neither
        is present, a fresh UUID v4 string is generated.
        """
        for header in _CORRELATION_HEADERS:
            value = request.headers.get(header, "").strip()
            if value:
                return value
        return str(uuid.uuid4())

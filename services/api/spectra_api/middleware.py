"""Request correlation, timing and access logging."""

from __future__ import annotations

import time
import uuid

from spectra_config.logging import get_logger, request_id_var
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from .metrics import METRICS

log = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
SLOW_REQUEST_MS = 2000.0


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Assigns a request id, times the request and records metrics."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming or f"req_{uuid.uuid4().hex[:16]}"
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        route = request.url.path
        try:
            response = await call_next(request)
        except Exception:
            elapsed = (time.perf_counter() - started) * 1000
            METRICS.record_request(route, 500, elapsed)
            log.error("http.request_failed", method=request.method, path=route, latency_ms=round(elapsed, 2))
            raise
        finally:
            request_id_var.reset(token)

        elapsed = (time.perf_counter() - started) * 1000
        METRICS.record_request(route, response.status_code, elapsed)
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers["X-Response-Time-Ms"] = f"{elapsed:.1f}"

        level = log.warning if elapsed > SLOW_REQUEST_MS else log.info
        level(
            "http.request",
            method=request.method,
            path=route,
            status=response.status_code,
            latency_ms=round(elapsed, 2),
        )
        return response

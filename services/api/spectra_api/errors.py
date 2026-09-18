"""Uniform error envelope for every failure the API can produce."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from spectra_config.logging import get_logger, request_id_var
from starlette.exceptions import HTTPException as StarletteHTTPException

log = get_logger(__name__)


class SpectraError(Exception):
    """Base class for errors that map cleanly onto the HTTP envelope."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "spectra_error"

    def __init__(self, reason: str, *, detail: dict[str, Any] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


class ValidationRejected(SpectraError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "validation_rejected"


class UploadRejected(SpectraError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "upload_rejected"


class PayloadTooLarge(SpectraError):
    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    code = "payload_too_large"


class SqlRejected(SpectraError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "sql_rejected"


class PermissionDenied(SpectraError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "permission_denied"


class NotFound(SpectraError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ConflictingState(SpectraError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflicting_state"


class BudgetExceeded(SpectraError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "budget_exceeded"


class DependencyUnavailable(SpectraError):
    """A backing service is down.  Always says which one and whether we degraded."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "dependency_unavailable"

    def __init__(self, dependency: str, reason: str, *, degraded_path_used: bool = False) -> None:
        super().__init__(reason, detail={"dependency": dependency, "degraded_path_used": degraded_path_used})


def _envelope(code: str, reason: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "error": code,
        "reason": reason,
        "request_id": request_id_var.get() or "",
        "detail": detail or {},
    }


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(SpectraError)
    async def _spectra(_: Request, exc: SpectraError) -> JSONResponse:
        log.warning("api.error", code=exc.code, reason=exc.reason, detail=exc.detail)
        return JSONResponse(status_code=exc.status_code, content=_envelope(exc.code, exc.reason, exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_envelope("schema_violation", "Request body failed validation", {"errors": exc.errors()}),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 403: "permission_denied", 405: "method_not_allowed"}.get(
            exc.status_code, "http_error"
        )
        return JSONResponse(status_code=exc.status_code, content=_envelope(code, str(exc.detail)))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.error("api.unhandled", error=str(exc), error_type=type(exc).__name__, exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope("internal_error", "An unexpected error occurred", {"type": type(exc).__name__}),
        )

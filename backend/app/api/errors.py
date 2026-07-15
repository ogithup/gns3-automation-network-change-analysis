"""Custom API exceptions and error handlers."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from app.api.models import ErrorResponse


class APIError(Exception):
    """Structured API exception."""

    def __init__(self, *, status_code: int, error: str, detail: str) -> None:
        self.status_code = status_code
        self.error = error
        self.detail = detail
        super().__init__(detail)


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=exc.error,
            detail=exc.detail,
            correlation_id=getattr(request.state, "correlation_id", None),
        ).model_dump(),
    )


async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="internal_error",
            detail=str(exc),
            correlation_id=getattr(request.state, "correlation_id", None),
        ).model_dump(),
    )

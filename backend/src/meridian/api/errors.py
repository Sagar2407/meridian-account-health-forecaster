"""The stable error contract (plan section 19.3).

Section 19.3 asks for stable codes a caller may branch on, plain user-facing
messages, and stack traces that stay in the log. All three are here, in one
place, so an endpoint cannot invent a fourth shape by accident.

The codes are `meridian.contracts.ErrorCode` -- the same vocabulary the graph
and the trace already use. A caller that has learned what `CRITICAL_DATA_GAP`
means from a decision does not have to learn a second meaning for it from an
HTTP response.
"""

import logging
from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from meridian.contracts import ErrorCode

logger = logging.getLogger("meridian.api")

#: The HTTP status each error code is reported with.
STATUS_FOR_CODE: dict[ErrorCode, int] = {
    "ACCOUNT_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "REQUEST_BLOCKED": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "CRITICAL_DATA_GAP": status.HTTP_200_OK,
    "MODEL_UNAVAILABLE": status.HTTP_503_SERVICE_UNAVAILABLE,
    "INDEX_VERSION_MISMATCH": status.HTTP_503_SERVICE_UNAVAILABLE,
    "RETRIEVAL_EXHAUSTED": status.HTTP_200_OK,
    "UNRESOLVED_CONFLICT": status.HTTP_200_OK,
    "VERIFICATION_FAILED": status.HTTP_200_OK,
    "INTERNAL_ERROR": status.HTTP_500_INTERNAL_SERVER_ERROR,
}


class ErrorResponse(BaseModel):
    """The one shape every failure is reported in."""

    code: ErrorCode
    message: str
    detail: dict[str, Any] | None = None


class ApiError(HTTPException):
    """An error carrying one of the contract's codes.

    Subclasses `HTTPException` so FastAPI's own handling still applies, and
    carries the code separately so the handler can render the documented body
    rather than FastAPI's default `{"detail": ...}`.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        http_status: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        resolved = http_status if http_status is not None else STATUS_FOR_CODE.get(code, 400)
        super().__init__(status_code=resolved, detail=message)
        self.code = code
        self.message = message
        self.payload = detail


async def api_error_handler(_: Request, error: Exception) -> JSONResponse:
    """Render an `ApiError` in the documented shape."""

    assert isinstance(error, ApiError)
    return JSONResponse(
        status_code=error.status_code,
        content=ErrorResponse(
            code=error.code, message=error.message, detail=error.payload
        ).model_dump(exclude_none=True),
    )


async def unhandled_error_handler(request: Request, error: Exception) -> JSONResponse:
    """Log the whole failure and return a message that reveals nothing.

    Section 24.3 forbids returning secrets or raw provider errors. A provider
    failure's message routinely contains a base URL, and sometimes a truncated
    key, so nothing from the exception reaches the response body.
    """

    logger.exception("unhandled error serving %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            code="INTERNAL_ERROR",
            message="The request could not be completed. The failure has been logged.",
        ).model_dump(exclude_none=True),
    )


__all__ = [
    "STATUS_FOR_CODE",
    "ApiError",
    "ErrorResponse",
    "api_error_handler",
    "unhandled_error_handler",
]

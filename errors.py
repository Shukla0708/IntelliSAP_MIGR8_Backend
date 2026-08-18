"""User-facing API errors. Never leak tracebacks, Bedrock bodies, or secrets."""
from __future__ import annotations

from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

STATUS_CODES = {
    "UNAUTHORIZED": 401,
    "FORBIDDEN": 403,
    "NOT_FOUND": 404,
    "CONFLICT": 409,
    "VALIDATION_ERROR": 422,
    "RATE_LIMITED": 429,
    "MAPPING_FAILED": 502,
    "LLM_UNAVAILABLE": 503,
    "SAP_UNREACHABLE": 503,
    "INTERNAL_ERROR": 500,
}

_HTTP_CODES = {
    400: "VALIDATION_ERROR",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
}


def request_id_of(request: Request | None) -> str:
    if request is None:
        return "-"
    return getattr(request.state, "request_id", None) or request.headers.get("x-request-id") or "-"


def error_payload(code: str, message: str, request_id: str = "-") -> dict:
    return {
        "error": {"code": code, "message": message, "request_id": request_id},
        "detail": message,
    }


def error_response(
    code: str,
    message: str,
    *,
    status_code: int | None = None,
    request_id: str = "-",
) -> JSONResponse:
    http_status = status_code or STATUS_CODES.get(code, 500)
    return JSONResponse(
        status_code=http_status,
        content=error_payload(code, message, request_id),
    )


def _http_exception_message(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        parts = []
        for item in detail:
            if isinstance(item, dict) and "msg" in item:
                parts.append(str(item["msg"]))
            else:
                parts.append(str(item))
        return ", ".join(parts) or "Request failed"
    return "Request failed"


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    code = _HTTP_CODES.get(exc.status_code, "INTERNAL_ERROR")
    if exc.status_code >= 500:
        code = "INTERNAL_ERROR"
        message = "Something went wrong. Please try again."
    else:
        message = _http_exception_message(exc)
    return error_response(
        code,
        message,
        status_code=exc.status_code,
        request_id=request_id_of(request),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    messages = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", []) if part != "body")
        msg = err.get("msg", "Invalid value")
        messages.append(f"{loc}: {msg}" if loc else msg)
    message = "; ".join(messages) or "Invalid request"
    return error_response(
        "VALIDATION_ERROR",
        message,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        request_id=request_id_of(request),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    del exc
    return error_response(
        "INTERNAL_ERROR",
        "Something went wrong. Please try again.",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        request_id=request_id_of(request),
    )

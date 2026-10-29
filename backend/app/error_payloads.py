"""Shared HTTP error payload helpers for backend routes."""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse


UPLOAD_FAILED_CODE = "UPLOAD_FAILED"
UPLOAD_FAILED_MESSAGE = "檔案上傳失敗"


def build_http_error(
    *,
    error_code: str,
    message: str,
    error: str,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "error_code": error_code,
        "message": message,
        "error": error,
    }
    payload.update(extra)
    return payload


def build_error_response(
    *,
    status_code: int,
    error_code: str,
    message: str,
    error: str,
    **extra: Any,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=build_http_error(
            error_code=error_code,
            message=message,
            error=error,
            **extra,
        ),
    )


def upload_failed_response(
    *,
    status_code: int,
    error: str,
    **extra: Any,
) -> JSONResponse:
    return build_error_response(
        status_code=status_code,
        error_code=UPLOAD_FAILED_CODE,
        message=UPLOAD_FAILED_MESSAGE,
        error=error,
        **extra,
    )


def upload_rejected_response(exc: Exception, **extra: Any) -> JSONResponse:
    """413 / 415 for a limit violation; ``detail`` carries the short reason."""
    from app.utils.upload import UnsupportedUploadError, UploadTooLargeError

    if isinstance(exc, UploadTooLargeError):
        status_code = 413
    elif isinstance(exc, UnsupportedUploadError):
        status_code = 415
    else:  # pragma: no cover - callers only pass the two limit errors
        raise TypeError(type(exc).__name__)
    message = str(exc)
    extra.setdefault("error", message)
    return upload_failed_response(
        status_code=status_code,
        detail=message,
        **extra,
    )

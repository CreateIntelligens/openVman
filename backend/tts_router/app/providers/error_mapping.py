"""Provider error classification for TTS routing."""

from __future__ import annotations

REASON_AUTH_ERROR = "auth_error"
REASON_RATE_LIMITED = "rate_limited"
REASON_BAD_REQUEST = "bad_request"
REASON_NETWORK_ERROR = "network_error"
REASON_PROVIDER_UNAVAILABLE = "provider_unavailable"
REASON_UNKNOWN = "unknown_error"


def classify_aws_error(exc: Exception) -> str:
    """Classify an AWS/botocore exception into a router reason code."""
    exc_type = type(exc).__name__
    message = str(exc).lower()

    # botocore ClientError carries a response dict
    response = getattr(exc, "response", None) or {}
    error_code = ""
    if isinstance(response, dict):
        error_code = response.get("Error", {}).get("Code", "").lower()

    # Auth / credentials
    if exc_type in ("NoCredentialsError", "PartialCredentialsError"):
        return REASON_AUTH_ERROR
    if error_code in ("unrecognizedclientexception", "invalididentitytokenexception"):
        return REASON_AUTH_ERROR
    if "credentials" in message or "access denied" in message:
        return REASON_AUTH_ERROR

    # Throttling
    if exc_type == "ThrottlingException" or error_code == "throttlingexception":
        return REASON_RATE_LIMITED
    if "throttl" in message or "rate" in message:
        return REASON_RATE_LIMITED

    # Bad request
    if error_code in ("invalidparametervalue", "validationexception"):
        return REASON_BAD_REQUEST
    if "texttoolong" in error_code or "invalid ssml" in message:
        return REASON_BAD_REQUEST

    # Network / timeout
    if exc_type in ("ConnectTimeoutError", "ReadTimeoutError", "EndpointConnectionError"):
        return REASON_NETWORK_ERROR
    if "timeout" in message or "connection" in message:
        return REASON_NETWORK_ERROR

    # Provider 5xx
    if exc_type == "ServiceUnavailableException":
        return REASON_PROVIDER_UNAVAILABLE
    status_code = response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
    if isinstance(status_code, int) and status_code >= 500:
        return REASON_PROVIDER_UNAVAILABLE

    return REASON_UNKNOWN


def classify_gcp_error(exc: Exception) -> str:
    """Classify a Google Cloud exception into a router reason code."""
    exc_type = type(exc).__name__
    message = str(exc).lower()

    # google.api_core.exceptions carry a grpc_status_code
    grpc_code = getattr(exc, "grpc_status_code", None)
    grpc_code_name = str(grpc_code).lower() if grpc_code else ""

    # Auth / credentials
    if "unauthenticated" in grpc_code_name or exc_type == "Unauthenticated":
        return REASON_AUTH_ERROR
    if "permission" in grpc_code_name or exc_type == "PermissionDenied":
        return REASON_AUTH_ERROR
    if "credentials" in message or "default credentials" in message:
        return REASON_AUTH_ERROR

    # Rate limited / quota
    if "resource_exhausted" in grpc_code_name or exc_type == "ResourceExhausted":
        return REASON_RATE_LIMITED
    if "quota" in message or "rate" in message:
        return REASON_RATE_LIMITED

    # Bad request
    if "invalid_argument" in grpc_code_name or exc_type == "InvalidArgument":
        return REASON_BAD_REQUEST

    # Unavailable / timeout
    if "unavailable" in grpc_code_name or exc_type == "ServiceUnavailable":
        return REASON_PROVIDER_UNAVAILABLE
    if "deadline_exceeded" in grpc_code_name or exc_type == "DeadlineExceeded":
        return REASON_PROVIDER_UNAVAILABLE
    if "timeout" in message:
        return REASON_PROVIDER_UNAVAILABLE

    return REASON_UNKNOWN


def _classify_http_error(exc: Exception, error_class: type) -> str:
    """Shared logic for HTTP-based TTS providers (httpx + custom error class)."""
    exc_type = type(exc).__name__
    message = str(exc).lower()

    # Custom error class with status code
    status_code = getattr(exc, "status_code", None)
    if status_code is not None and isinstance(exc, error_class):
        if status_code == 422:
            return REASON_BAD_REQUEST
        if status_code >= 500:
            return REASON_PROVIDER_UNAVAILABLE

    # httpx timeouts
    if exc_type in ("TimeoutException", "ReadTimeout", "ConnectTimeout", "PoolTimeout"):
        return REASON_NETWORK_ERROR
    if "timeout" in message:
        return REASON_NETWORK_ERROR

    # httpx connection errors
    if exc_type in ("ConnectError", "RemoteProtocolError"):
        return REASON_NETWORK_ERROR
    if "connection" in message or "refused" in message:
        return REASON_NETWORK_ERROR

    return REASON_UNKNOWN


def classify_node_error(exc: Exception) -> str:
    """Classify an error from a self-hosted TTS node."""
    from app.providers.node_adapter import NodeHTTPError
    return _classify_http_error(exc, NodeHTTPError)


def classify_index_error(exc: Exception) -> str:
    """Classify an error from an Index TTS node."""
    from app.providers.index_tts_adapter import IndexTTSHTTPError
    return _classify_http_error(exc, IndexTTSHTTPError)

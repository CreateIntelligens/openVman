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


def _classify_network_error(exc: Exception) -> str | None:
    """Check for common network/timeout errors. Returns reason or None."""
    exc_type = type(exc).__name__
    message = str(exc).lower()

    if exc_type in ("TimeoutException", "ReadTimeout", "ConnectTimeout", "PoolTimeout"):
        return REASON_NETWORK_ERROR
    if exc_type in ("ConnectError", "RemoteProtocolError"):
        return REASON_NETWORK_ERROR
    if "timeout" in message or "connection" in message or "refused" in message:
        return REASON_NETWORK_ERROR

    return None


def _classify_http_provider_error(exc: Exception, error_class: type) -> str:
    """Classify an HTTP provider error by status code."""
    if isinstance(exc, error_class):
        if exc.status_code == 422:
            return REASON_BAD_REQUEST
        if exc.status_code >= 500:
            return REASON_PROVIDER_UNAVAILABLE
    return _classify_network_error(exc) or REASON_UNKNOWN


def classify_indextts_error(exc: Exception) -> str:
    from app.providers.indextts_adapter import IndexTTSHTTPError
    return _classify_http_provider_error(exc, IndexTTSHTTPError)


def classify_vibevoice_error(exc: Exception) -> str:
    from app.providers.vibevoice_adapter import VibeVoiceHTTPError
    return _classify_http_provider_error(exc, VibeVoiceHTTPError)


def classify_edge_tts_error(exc: Exception) -> str:
    """Classify an error from in-process Edge-TTS."""
    from app.providers.edge_tts_adapter import EdgeTTSError

    if isinstance(exc, EdgeTTSError):
        return REASON_BAD_REQUEST

    return _classify_network_error(exc) or REASON_UNKNOWN

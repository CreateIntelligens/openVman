from __future__ import annotations

from fastapi import APIRouter, Depends

from protocol.protocol_events import (
    ProtocolValidationError,
    validate_client_event,
    validate_server_event,
)
from protocol.schemas import ProtocolValidateRequest
from safety.internal_auth import require_internal_token

router = APIRouter(
    prefix="/brain",
    tags=["Protocol"],
    dependencies=[Depends(require_internal_token)],
)


@router.post("/protocol/validate", summary="驗證傳輸協定格式")
async def protocol_validate(payload: ProtocolValidateRequest):
    try:
        if payload.direction == "client_to_server":
            event = validate_client_event(payload.payload, payload.version)
        else:
            event = validate_server_event(payload.payload, payload.version)
    except ProtocolValidationError as exc:
        return {
            "valid": False,
            "event": exc.event,
            "version": exc.version,
            "error": str(exc),
            "details": exc.details,
        }
    return {"valid": True, "event": event.event, "version": payload.version}

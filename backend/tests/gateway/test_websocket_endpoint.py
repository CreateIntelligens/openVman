from __future__ import annotations

import pytest

from app.gateway import websocket as websocket_routes
from app.session_manager import SessionManager


class DisconnectedReceiveWebSocket:
    client_state = type("State", (), {"name": "DISCONNECTED"})()

    def __init__(self) -> None:
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def receive_text(self) -> str:
        raise RuntimeError('WebSocket is not connected. Need to call "accept" first.')


@pytest.mark.asyncio
async def test_websocket_endpoint_treats_closed_receive_runtimeerror_as_disconnect(monkeypatch):
    disconnects: list[str] = []
    errors: list[str] = []

    monkeypatch.setattr(websocket_routes, "_session_manager", SessionManager())
    monkeypatch.setattr(websocket_routes, "record_ws_disconnect", lambda reason: disconnects.append(reason))
    monkeypatch.setattr(websocket_routes, "record_ws_error", lambda error_type: errors.append(error_type))
    monkeypatch.setattr(websocket_routes, "set_active_sessions", lambda _count: None)

    websocket = DisconnectedReceiveWebSocket()
    await websocket_routes.websocket_endpoint(websocket, "client-closed")

    assert websocket.accepted is True
    assert disconnects == ["client"]
    assert errors == []

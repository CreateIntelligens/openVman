from __future__ import annotations

import asyncio
import uuid
from typing import Dict, Optional, List, Any
from fastapi import WebSocket


class Session:
    """Represents an active WebSocket session."""
    def __init__(self, client_id: str, websocket: Optional[WebSocket] = None):
        self.session_id: str = uuid.uuid4().hex
        self.client_id: str = client_id
        self.websocket: Optional[WebSocket] = websocket
        self.active_tasks: List[asyncio.Task] = []
        self.background_tasks: List[asyncio.Task] = []
        self.lip_sync_mode: str = "dinet"
        self.metadata: Dict[str, Any] = {}
        self.brain_live_relay: Any = None

    def set_websocket(self, websocket: WebSocket) -> None:
        """Update the websocket connection for this session."""
        self.websocket = websocket

    def add_task(self, task: asyncio.Task, *, interruptible: bool = True) -> None:
        """Track a task for session lifecycle cleanup."""
        target = self.active_tasks if interruptible else self.background_tasks
        target.append(task)
        task.add_done_callback(lambda t: target.remove(t) if t in target else None)

    async def interrupt_tasks(self) -> int:
        """Cancel interruptible tasks for this session."""
        return await self._cancel_task_collection(self.active_tasks)

    async def cancel_all_tasks(self) -> int:
        """Cancel both interruptible and background tasks."""
        cancelled_count = await self._cancel_task_collection(self.active_tasks)
        cancelled_count += await self._cancel_task_collection(self.background_tasks)
        return cancelled_count

    async def _cancel_task_collection(self, tasks: List[asyncio.Task]) -> int:
        pending = [t for t in tasks if not t.done()]
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        tasks[:] = []
        return len(pending)


class SessionManager:
    """Manages active WebSocket sessions."""

    def __init__(self) -> None:
        self.active_sessions: Dict[str, Session] = {}

    def create_session(self, client_id: str, websocket: Optional[WebSocket] = None) -> Session:
        """Create a new session for a client."""
        session = Session(client_id=client_id, websocket=websocket)
        self.active_sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """Retrieve a session by its ID."""
        return self.active_sessions.get(session_id)

    def remove_session(self, session_id: str) -> None:
        """Remove a session from the manager."""
        if session_id in self.active_sessions:
            del self.active_sessions[session_id]

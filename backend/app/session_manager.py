from __future__ import annotations

import asyncio
import uuid
from typing import Dict, Optional, List


class Session:
    """Represents an active WebSocket session."""
    def __init__(self, client_id: str):
        self.session_id: str = uuid.uuid4().hex
        self.client_id: str = client_id
        # To track active asyncio tasks (e.g. Brain generation or TTS synthesis)
        self.active_tasks: List[asyncio.Task] = []

    def add_task(self, task: asyncio.Task) -> None:
        """Add a task to the session's active tasks."""
        self.active_tasks.append(task)
        # Automatically remove task from list when it's done
        task.add_done_callback(lambda t: self.active_tasks.remove(t) if t in self.active_tasks else None)

    async def interrupt_tasks(self) -> int:
        """Cancel all active tasks for this session."""
        cancelled_count = 0
        for task in self.active_tasks:
            if not task.done():
                task.cancel()
                cancelled_count += 1
        
        # Optionally wait for all tasks to acknowledge cancellation
        if cancelled_count > 0:
            await asyncio.gather(*self.active_tasks, return_exceptions=True)
            self.active_tasks = []
            
        return cancelled_count


class SessionManager:
    """Manages active WebSocket sessions."""

    def __init__(self) -> None:
        self.active_sessions: Dict[str, Session] = {}

    def create_session(self, client_id: str) -> Session:
        """Create a new session for a client."""
        session = Session(client_id=client_id)
        self.active_sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """Retrieve a session by its ID."""
        return self.active_sessions.get(session_id)

    def remove_session(self, session_id: str) -> None:
        """Remove a session from the manager."""
        if session_id in self.active_sessions:
            del self.active_sessions[session_id]

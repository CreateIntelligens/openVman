"""Identity, settings and event delivery shared by a Gemini Live session's parts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable


EventSink = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class LiveSessionContext:
    """What every Live collaborator may read; none of them owns or changes it."""

    relay_session_id: str
    session_id: str
    persona_id: str
    project_id: str
    user_id: str
    role: str
    principal_type: str
    principal_id: str
    config: Any
    event_sink: EventSink | None = None

    async def emit(self, event: dict[str, Any]) -> None:
        if self.event_sink is not None:
            await self.event_sink(event)

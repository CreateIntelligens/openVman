"""Stop a chat generation whose HTTP caller has gone away.

``POST /brain/chat`` binds a ``threading.Event`` for the request and sets it when
the client disconnects. Generation runs in worker threads (``asyncio.to_thread``
copies context vars, and the tool executor re-enters the parent context), so the
agent loop and LLM client read the event from a context var and call
``raise_if_cancelled`` at safe points: before each LLM call or fallback hop,
between streamed chunks, and before each tool round. A request already sent to a
provider cannot be recalled; only the next step is skipped.
"""

from __future__ import annotations

import contextvars
import threading
from collections.abc import Iterator
from contextlib import contextmanager


class GenerationCancelled(Exception):
    """The caller disconnected; *stage* says where generation noticed."""

    def __init__(self, stage: str, *, tool_steps: int = 0) -> None:
        super().__init__(f"generation cancelled at {stage}")
        self.stage = stage
        self.tool_steps = tool_steps


_cancel_event: contextvars.ContextVar[threading.Event | None] = contextvars.ContextVar(
    "generation_cancel_event", default=None,
)


@contextmanager
def bind_cancel_event(event: threading.Event) -> Iterator[threading.Event]:
    token = _cancel_event.set(event)
    try:
        yield event
    finally:
        _cancel_event.reset(token)


def current_cancel_event() -> threading.Event | None:
    return _cancel_event.get()


def is_cancelled() -> bool:
    event = _cancel_event.get()
    return event is not None and event.is_set()


def raise_if_cancelled(stage: str, *, tool_steps: int = 0) -> None:
    if is_cancelled():
        raise GenerationCancelled(stage, tool_steps=tool_steps)

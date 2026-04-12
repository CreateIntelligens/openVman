from __future__ import annotations

import asyncio

import pytest

from app.session_manager import Session


@pytest.mark.asyncio
async def test_session_interrupt_tasks_skips_non_interruptible_tasks():
    session = Session("client-heartbeat")
    cancelled = asyncio.Event()

    async def _background_task() -> None:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    task = asyncio.create_task(_background_task())
    session.add_task(task, interruptible=False)

    try:
        cancelled_count = await session.interrupt_tasks()

        assert cancelled_count == 0
        assert cancelled.is_set() is False
        assert task.done() is False
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

"""Optional Jev pre-filter: skip Brain only when Jev is near-certain no reply is needed."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.config import TTSRouterConfig
from app.gateway.a2a_bridge import A2ABridgeDaemon
from app.gateway.a2a_client import A2AClient
from app.gateway.a2a_queue import A2AWorkQueue
from app.gateway.a2a_store import A2ACredentialStore


async def _daemon_with_event(tmp_path: Path, message: str, **cfg_overrides):
    queue = A2AWorkQueue(tmp_path / "work.db")
    client = AsyncMock(spec=A2AClient)
    client.acknowledge_task.return_value = True
    cfg = TTSRouterConfig(a2a_enabled=True, typesafe_api_key="k", **cfg_overrides)
    daemon = A2ABridgeDaemon(
        config=cfg, store=A2ACredentialStore(tmp_path / "creds.json"), queue=queue, client=client,
    )
    await daemon._on_raw_task_received("scope", {
        "sequence": 1, "taskId": "task-1", "requesterAgentId": "peer", "message": message,
    })
    return daemon, queue.get_unprocessed_events("scope")[0], client


def _jev(choice: str, no_reply: float):
    return AsyncMock(return_value={
        "choice": choice, "probabilities": {"no_reply": no_reply, "reply": 1 - no_reply},
    })


@pytest.mark.asyncio
async def test_confident_no_reply_skips_brain(tmp_path):
    daemon, event, client = await _daemon_with_event(
        tmp_path, "收到，謝謝！", a2a_jev_prefilter_enabled=True,
    )
    with patch("app.jev_client.jev_answer", _jev("no_reply", 0.97)), \
         patch.object(daemon, "_query_brain", new_callable=AsyncMock) as brain:
        await daemon._process_queued_event(event)
    brain.assert_not_called()
    client.send_task.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [
    _jev("no_reply", 0.7),   # 不夠確定
    _jev("reply", 0.05),
    AsyncMock(side_effect=RuntimeError("down")),
])
async def test_anything_less_than_certain_goes_to_brain(tmp_path, answer):
    daemon, event, _ = await _daemon_with_event(
        tmp_path, "收到。另外想問退貨期限？", a2a_jev_prefilter_enabled=True,
    )
    with patch("app.jev_client.jev_answer", answer), \
         patch.object(daemon, "_query_brain", new_callable=AsyncMock) as brain:
        brain.return_value = "退貨期限是七天。"
        await daemon._process_queued_event(event)
    brain.assert_awaited_once()


@pytest.mark.asyncio
async def test_disabled_by_default(tmp_path):
    daemon, event, _ = await _daemon_with_event(tmp_path, "收到，謝謝！")
    jev = _jev("no_reply", 0.99)
    with patch("app.jev_client.jev_answer", jev), \
         patch.object(daemon, "_query_brain", new_callable=AsyncMock) as brain:
        brain.return_value = "好的。"
        await daemon._process_queued_event(event)
    jev.assert_not_called()
    brain.assert_awaited_once()

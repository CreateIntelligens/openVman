"""Unit tests for A2ABridgeDaemon with durable work queue and anti-echo guard."""

from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest

from app.config import TTSRouterConfig
from app.gateway.a2a_bridge import A2ABridgeDaemon, _NO_REPLY_TOKEN
from app.gateway.a2a_client import A2AClient
from app.gateway.a2a_queue import A2AWorkQueue
from app.gateway.a2a_store import A2ACredentialStore, A2ACredentials, compute_key_fingerprint


@pytest.mark.asyncio
async def test_bridge_enqueue_before_ack_and_reply(tmp_path: Path):
    creds_file = tmp_path / "creds.json"
    queue_file = tmp_path / "work.db"

    store = A2ACredentialStore(creds_file, encryption_key="test-encryption-key")
    queue = A2AWorkQueue(queue_file)

    creds = A2ACredentials(
        agentId="openvman-1",
        agentToken="token-1",
        circleId="test-private-circle",
        hubUrl="https://a2a.david888.com",
        hubKeyFingerprint=compute_key_fingerprint("test-private-circle", "test-encryption-key"),
    )
    store.save(creds)

    mock_client = AsyncMock(spec=A2AClient)
    mock_client.acknowledge_task.return_value = True
    mock_client.send_task.return_value = {"status": "QUEUED"}

    cfg = TTSRouterConfig(
        a2a_enabled=True,
        a2a_credentials_path=str(creds_file),
        a2a_queue_db_path=str(queue_file),
    )
    daemon = A2ABridgeDaemon(config=cfg, store=store, queue=queue, client=mock_client)

    inbound_task = {
        "sequence": 10,
        "taskId": "task-uuid-1",
        "requesterAgentId": "openclaw-agent",
        "contextId": "ctx-1",
        "message": "What is openVman?",
    }

    # Step 1: Inbound SSE event triggers durable enqueue and immediate ACK
    await daemon._on_raw_task_received("test-scope", inbound_task)
    mock_client.acknowledge_task.assert_called_once_with(10)

    # Verify committed into SQLite WAL queue before processing
    events = queue.get_unprocessed_events("test-scope")
    assert len(events) == 1
    assert events[0]["sequence"] == 10
    assert events[0]["status"] == "ACKNOWLEDGED"

    # Step 2: Worker processes the queued event
    with patch.object(daemon, "_query_brain", new_callable=AsyncMock) as mock_brain:
        mock_brain.return_value = "openVman is a 3D avatar agent platform."
        await daemon._process_queued_event(events[0])

        mock_brain.assert_called_once_with(
            "What is openVman?",
            requester_id="openclaw-agent",
            task_id="task-uuid-1",
            context_id="ctx-1",
        )
        mock_client.send_task.assert_called_once()
        call_kwargs = mock_client.send_task.call_args.kwargs
        assert call_kwargs["target_agent_id"] == "openclaw-agent"
        assert call_kwargs["message"] == "openVman is a 3D avatar agent platform."


@pytest.mark.asyncio
async def test_bridge_anti_echo_suppression(tmp_path: Path):
    creds_file = tmp_path / "creds.json"
    queue_file = tmp_path / "work.db"

    store = A2ACredentialStore(creds_file)
    queue = A2AWorkQueue(queue_file)

    mock_client = AsyncMock(spec=A2AClient)
    mock_client.acknowledge_task.return_value = True

    cfg = TTSRouterConfig(a2a_enabled=True)
    daemon = A2ABridgeDaemon(config=cfg, store=store, queue=queue, client=mock_client)

    inbound_task = {
        "sequence": 11,
        "taskId": "task-uuid-2",
        "requesterAgentId": "openclaw-agent",
        "message": "收錄完畢，保持連線待命",
    }

    await daemon._on_raw_task_received("test-scope", inbound_task)
    mock_client.acknowledge_task.assert_called_once_with(11)

    events = queue.get_unprocessed_events("test-scope")
    assert len(events) == 1

    with patch.object(daemon, "_query_brain", new_callable=AsyncMock) as mock_brain:
        mock_brain.return_value = _NO_REPLY_TOKEN
        await daemon._process_queued_event(events[0])
        # Brain decides suppression; transport must not hardcode a phrase shortcut.
        mock_brain.assert_called_once()
        mock_client.send_task.assert_not_called()


@pytest.mark.asyncio
async def test_bridge_token_suppression(tmp_path: Path):
    creds_file = tmp_path / "creds.json"
    queue_file = tmp_path / "work.db"

    store = A2ACredentialStore(creds_file)
    queue = A2AWorkQueue(queue_file)

    mock_client = AsyncMock(spec=A2AClient)
    mock_client.acknowledge_task.return_value = True

    cfg = TTSRouterConfig(a2a_enabled=True)
    daemon = A2ABridgeDaemon(config=cfg, store=store, queue=queue, client=mock_client)

    inbound_task = {
        "sequence": 12,
        "taskId": "task-uuid-3",
        "requesterAgentId": "openclaw-agent",
        "message": "System status update.",
    }

    await daemon._on_raw_task_received("test-scope", inbound_task)
    events = queue.get_unprocessed_events("test-scope")

    with patch.object(daemon, "_query_brain", new_callable=AsyncMock) as mock_brain:
        mock_brain.return_value = f"Status noted. {_NO_REPLY_TOKEN}"
        await daemon._process_queued_event(events[0])
        mock_client.send_task.assert_not_called()

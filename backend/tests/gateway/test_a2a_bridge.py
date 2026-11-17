"""Unit tests for A2ABridgeDaemon with durable work queue and anti-echo guard."""

import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
from unittest.mock import AsyncMock, patch
import httpx
import pytest

from app.config import TTSRouterConfig
from app.gateway.a2a_bridge import (
    A2ABridgeDaemon,
    A2ACredentialsUnavailableError,
    _NO_REPLY_TOKEN,
)
from app.gateway.a2a_client import A2AClient, A2ARateLimitError, A2ARateLimiter
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


@pytest.mark.asyncio
async def test_conservative_leader_election_on_redis_failure(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("BACKEND_WORKERS", raising=False)
    store = A2ACredentialStore(tmp_path / "creds.json", "test")
    queue = A2AWorkQueue(tmp_path / "work.db")

    # Single-process dev mode may still assume standalone leadership without Redis.
    single_dev = TTSRouterConfig(
        _env_file=None,
        env="dev",
        backend_workers=1,
        a2a_enabled=True,
        a2a_credentials_path=str(tmp_path / "creds.json"),
        a2a_queue_db_path=str(tmp_path / "work.db"),
    )
    d_single = A2ABridgeDaemon(config=single_dev, store=store, queue=queue)

    # Multi-process dev mode MUST NOT assume leadership when Redis is unavailable.
    multi_dev = TTSRouterConfig(
        _env_file=None,
        env="dev",
        backend_workers=4,
        a2a_enabled=True,
        a2a_credentials_path=str(tmp_path / "creds.json"),
        a2a_queue_db_path=str(tmp_path / "work.db"),
    )
    d_multi = A2ABridgeDaemon(config=multi_dev, store=store, queue=queue)

    with patch("app.gateway.a2a_bridge.get_redis", new_callable=AsyncMock, return_value=None):
        assert await d_single._acquire_leader_lease() is True
        assert await d_single._renew_leader_lease() is True
        assert await d_multi._acquire_leader_lease() is False
        assert await d_multi._renew_leader_lease() is False


@pytest.mark.asyncio
async def test_non_leader_reloads_credentials_on_mtime_and_401(tmp_path: Path):
    creds_file = tmp_path / "creds.json"
    queue_file = tmp_path / "work.db"
    enc_key = "test-enc-key"
    hub_url = "https://a2a.david888.com"
    hub_key = "test-circle"
    store = A2ACredentialStore(creds_file, encryption_key=enc_key)
    queue = A2AWorkQueue(queue_file)

    cfg = TTSRouterConfig(
        a2a_enabled=True,
        a2a_hub_url=hub_url,
        a2a_hub_key=hub_key,
        a2a_credentials_path=str(creds_file),
        a2a_credentials_encryption_key=enc_key,
        a2a_queue_db_path=str(queue_file),
        backend_workers=4,
    )
    non_leader = A2ABridgeDaemon(config=cfg, store=store, queue=queue)
    assert non_leader.is_leader is False

    # Missing file fails closed
    with pytest.raises(A2ACredentialsUnavailableError):
        await non_leader.call_outbound(lambda c: c.list_peers())

    # Leader saves initial credentials
    creds_v1 = A2ACredentials(
        agentId="agent-1",
        agentToken="token-v1",
        circleId="test-circle",
        hubUrl=hub_url,
        hubKeyFingerprint=compute_key_fingerprint(hub_key, enc_key),
    )
    store.save(creds_v1)

    seen_tokens: list[str] = []

    async def fake_op(client: A2AClient):
        token = client.credentials.agent_token if client.credentials else ""
        seen_tokens.append(token)
        if token == "token-v1":
            # Simulate leader rotating credentials right before/during an auth failure
            creds_v2 = A2ACredentials(
                agentId="agent-1",
                agentToken="token-v2",
                circleId="test-circle",
                hubUrl=hub_url,
                hubKeyFingerprint=compute_key_fingerprint(hub_key, enc_key),
            )
            store.save(creds_v2)
            req = httpx.Request("GET", f"{hub_url}/hub/v1/agents")
            resp = httpx.Response(401, request=req)
            raise httpx.HTTPStatusError("401", request=req, response=resp)
        return [{"agentId": "peer-1"}]

    peers = await non_leader.call_outbound(fake_op)
    assert peers == [{"agentId": "peer-1"}]
    assert seen_tokens == ["token-v1", "token-v2"]

    # Direct mtime change without 401 also reloads automatically
    creds_v3 = A2ACredentials(
        agentId="agent-1",
        agentToken="token-v3",
        circleId="test-circle",
        hubUrl=hub_url,
        hubKeyFingerprint=compute_key_fingerprint(hub_key, enc_key),
    )
    store.save(creds_v3)
    st = creds_file.stat()
    os.utime(creds_file, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))

    async def capture_token(client: A2AClient):
        return client.credentials.agent_token

    assert await non_leader.call_outbound(capture_token) == "token-v3"

    # Clearing credentials invalidates cached client
    store.clear()
    with pytest.raises(A2ACredentialsUnavailableError):
        await non_leader.call_outbound(capture_token)


def test_queue_requeue_processing_events_recovers_interrupted_work(tmp_path: Path):
    q = A2AWorkQueue(tmp_path / "work.db")
    q.enqueue_event("hub-1", 1, "task-1", "peer-a", "msg-1")
    q.mark_ack_dispatched("hub-1", 1)
    events = q.get_unprocessed_events("hub-1")
    assert len(events) == 1
    assert q.record_processing_start(events[0]["id"]) is True
    # Already PROCESSING -> second claim rejected
    assert q.record_processing_start(events[0]["id"]) is False
    assert q.get_unprocessed_events("hub-1") == []

    # New leader recovers interrupted PROCESSING events
    recovered = q.requeue_processing_events("hub-1")
    assert recovered == 1
    events_after = q.get_unprocessed_events("hub-1")
    assert len(events_after) == 1
    assert events_after[0]["attempts"] == 1


@pytest.mark.asyncio
async def test_slow_ack_over_5s_does_not_busy_spin_ack_worker_loop(tmp_path: Path):
    creds_file = tmp_path / "creds.json"
    queue_file = tmp_path / "work.db"
    store = A2ACredentialStore(creds_file, "test-secret")
    queue = A2AWorkQueue(queue_file)

    ack_started = asyncio.Event()
    ack_release = asyncio.Event()

    async def slow_ack(sequence: int) -> bool:
        ack_started.set()
        await ack_release.wait()
        return True

    mock_client = AsyncMock(spec=A2AClient)
    mock_client.acknowledge_task.side_effect = slow_ack

    cfg = TTSRouterConfig(
        a2a_enabled=True,
        a2a_credentials_path=str(creds_file),
        a2a_queue_db_path=str(queue_file),
    )
    daemon = A2ABridgeDaemon(config=cfg, store=store, queue=queue, client=mock_client)

    raw_task = asyncio.create_task(
        daemon._on_raw_task_received(
            "test-scope",
            {
                "sequence": 1,
                "taskId": "slow-ack-task",
                "requesterAgentId": "openclaw-agent",
                "message": "ping",
            },
        )
    )
    await asyncio.wait_for(ack_started.wait(), timeout=2.0)

    # Simulate elapsed >5s past initial_next_ack_at while instant ACK is still in _inflight_acks.
    past_iso = datetime.fromtimestamp(0.0, tz=timezone.utc).isoformat()
    with sqlite3.connect(str(queue_file)) as conn:
        conn.execute(
            "UPDATE a2a_inbox_events SET next_ack_at = ? WHERE sequence = 1",
            (past_iso,),
        )
        conn.commit()

    poll_count = 0
    orig_get_pending = queue.get_pending_ack_events

    def tracked_get_pending(hub_scope: str, limit: int = 20):
        nonlocal poll_count
        poll_count += 1
        return orig_get_pending(hub_scope, limit=limit)

    queue.get_pending_ack_events = tracked_get_pending  # type: ignore[method-assign]
    daemon._running = True
    daemon._is_leader = True
    ack_worker = asyncio.create_task(daemon._ack_worker_loop())

    # Other coroutines must continue scheduling cleanly without CPU busy-spin.
    await asyncio.sleep(0.15)
    assert poll_count <= 2

    ack_release.set()
    await asyncio.wait_for(raw_task, timeout=2.0)
    daemon._running = False
    daemon._is_leader = False
    ack_worker.cancel()
    await asyncio.gather(ack_worker, return_exceptions=True)

    mock_client.acknowledge_task.assert_awaited_once_with(1)
    assert len(queue.get_unprocessed_events("test-scope")) == 1


@pytest.mark.asyncio
async def test_losing_leader_lease_cancels_inflight_processing_and_prevents_duplicate_brain_calls(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("BACKEND_WORKERS", raising=False)
    queue_file = tmp_path / "work.db"
    creds_file = tmp_path / "creds.json"
    store = A2ACredentialStore(creds_file, "test-secret")
    queue = A2AWorkQueue(queue_file)
    cfg = TTSRouterConfig(
        _env_file=None,
        a2a_enabled=True,
        a2a_credentials_path=str(creds_file),
        a2a_queue_db_path=str(queue_file),
        a2a_max_concurrency=1,
        a2a_leader_lease_ttl_seconds=5,
        backend_workers=4,
    )

    client_a = AsyncMock(spec=A2AClient)
    client_b = AsyncMock(spec=A2AClient)
    daemon_a = A2ABridgeDaemon(config=cfg, store=store, queue=queue, client=client_a)
    daemon_b = A2ABridgeDaemon(config=cfg, store=store, queue=queue, client=client_b)

    scope = daemon_a._hub_scope()
    queue.enqueue_event(scope, 1, "task-1", "peer-a", "hello-1")
    queue.mark_ack_dispatched(scope, 1)
    queue.enqueue_event(scope, 2, "task-2", "peer-a", "hello-2")
    queue.mark_ack_dispatched(scope, 2)

    lease_holder = {"id": "a"}
    a_brain_entered = asyncio.Event()
    a_brain_cancelled = asyncio.Event()
    a_brain_calls: list[str] = []
    b_brain_calls: list[str] = []

    async def slow_brain_a(message: str, **kwargs):
        a_brain_calls.append(kwargs["task_id"])
        a_brain_entered.set()
        try:
            await asyncio.sleep(10.0)
        except asyncio.CancelledError:
            a_brain_cancelled.set()
            raise
        return "stale-reply-from-a"

    async def fast_brain_b(message: str, **kwargs):
        b_brain_calls.append(kwargs["task_id"])
        return f"reply-from-b:{message}"

    async def _idle_stream():
        await asyncio.sleep(10.0)

    daemon_a._acquire_leader_lease = AsyncMock(side_effect=lambda: lease_holder["id"] == "a")  # type: ignore[method-assign]
    daemon_a._renew_leader_lease = AsyncMock(side_effect=lambda: lease_holder["id"] == "a")  # type: ignore[method-assign]
    daemon_a._release_leader_lease = AsyncMock()  # type: ignore[method-assign]
    daemon_a._run_sse_stream = AsyncMock(side_effect=_idle_stream)  # type: ignore[method-assign]
    daemon_a._query_brain = AsyncMock(side_effect=slow_brain_a)  # type: ignore[method-assign]

    daemon_b._acquire_leader_lease = AsyncMock(side_effect=lambda: lease_holder["id"] == "b")  # type: ignore[method-assign]
    daemon_b._renew_leader_lease = AsyncMock(side_effect=lambda: lease_holder["id"] == "b")  # type: ignore[method-assign]
    daemon_b._release_leader_lease = AsyncMock()  # type: ignore[method-assign]
    daemon_b._run_sse_stream = AsyncMock(side_effect=_idle_stream)  # type: ignore[method-assign]
    daemon_b._query_brain = AsyncMock(side_effect=fast_brain_b)  # type: ignore[method-assign]

    daemon_a.start()
    await asyncio.wait_for(a_brain_entered.wait(), timeout=3.0)

    # Abdicate A: renew now returns False -> A must cancel in-flight Brain work and never run task-2.
    lease_holder["id"] = "none"
    await asyncio.wait_for(a_brain_cancelled.wait(), timeout=3.0)
    for _ in range(40):
        if not daemon_a.is_leader and not daemon_a._processing_tasks:
            break
        await asyncio.sleep(0.05)

    assert daemon_a.is_leader is False
    client_a.send_task.assert_not_called()
    assert a_brain_calls == ["task-1"]

    # Guard on direct call must also block Brain when no longer leader.
    unprocessed_before_b = queue.get_unprocessed_events(scope, limit=10)
    assert [ev["task_id"] for ev in unprocessed_before_b] == ["task-1", "task-2"]
    assert unprocessed_before_b[0]["attempts"] == 0
    await daemon_a._process_queued_event(unprocessed_before_b[1], require_leader=True)
    assert a_brain_calls == ["task-1"]

    # Promote B: B completes both tasks once each.
    lease_holder["id"] = "b"
    daemon_b.start()
    for _ in range(60):
        if client_b.send_task.await_count == 2:
            break
        await asyncio.sleep(0.05)

    await daemon_a.stop()
    await daemon_b.stop()

    assert b_brain_calls == ["task-1", "task-2"]
    assert client_b.send_task.await_count == 2


@pytest.mark.asyncio
async def test_rate_limited_reply_defers_by_retry_after_without_counting_failure(tmp_path: Path):
    queue_file = tmp_path / "work.db"
    creds_file = tmp_path / "creds.json"
    store = A2ACredentialStore(creds_file, "test-secret")
    queue = A2AWorkQueue(queue_file)
    mock_client = AsyncMock(spec=A2AClient)
    # Fail with rate limit 6 times (> 5-attempt failure threshold), then succeed.
    mock_client.send_task.side_effect = [
        *[A2ARateLimitError(retry_after=2, max_calls=1) for _ in range(6)],
        {"status": "QUEUED"},
    ]

    cfg = TTSRouterConfig(
        a2a_enabled=True,
        a2a_credentials_path=str(creds_file),
        a2a_queue_db_path=str(queue_file),
    )
    daemon = A2ABridgeDaemon(config=cfg, store=store, queue=queue, client=mock_client)
    scope = "test-scope"
    queue.enqueue_event(scope, 1, "task-rl", "peer-a", "hello rate limit")
    queue.mark_ack_dispatched(scope, 1)

    with patch.object(daemon, "_query_brain", new_callable=AsyncMock, return_value="Saved Brain Reply") as mock_brain:
        events = queue.get_unprocessed_events(scope)
        await daemon._process_queued_event(events[0])

        # Must be deferred in SQLite with exponential backoff (attempts=1), NOT hidden or stopped after 5 attempts.
        assert queue.get_unprocessed_events(scope) == []
        with sqlite3.connect(str(queue_file)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM a2a_inbox_events WHERE task_id = 'task-rl'").fetchone()
            assert row["status"] == "ACKNOWLEDGED"
            assert row["attempts"] == 1
            assert row["next_retry_at"] is not None
            assert row["reply_message"] == "Saved Brain Reply"

        # Simulate elapsed retry_after across 5 more rate-limit cycles + final success.
        past_iso = datetime.fromtimestamp(0.0, tz=timezone.utc).isoformat()
        for _ in range(6):
            with sqlite3.connect(str(queue_file)) as conn:
                conn.execute("UPDATE a2a_inbox_events SET next_retry_at = ? WHERE task_id = 'task-rl'", (past_iso,))
                conn.commit()
            ready = queue.get_unprocessed_events(scope)
            assert len(ready) == 1
            await daemon._process_queued_event(ready[0])

        # Brain called once only; reply never lost to FAILED; finally COMPLETED.
        mock_brain.assert_awaited_once()
        assert mock_client.send_task.await_count == 7
        with sqlite3.connect(str(queue_file)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM a2a_inbox_events WHERE task_id = 'task-rl'").fetchone()
            assert row["status"] == "COMPLETED"
            assert row["next_retry_at"] is None


@pytest.mark.asyncio
async def test_401_retry_does_not_consume_extra_rate_limit_slot(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("BACKEND_WORKERS", raising=False)
    creds_file = tmp_path / "creds.json"
    queue_file = tmp_path / "work.db"
    enc_key = "test-secret"
    hub_url = "https://hub.example"
    hub_key = "circle-secret"
    store = A2ACredentialStore(creds_file, enc_key)
    store.save(
        A2ACredentials(
            agentId="agent-1",
            agentToken="tok-v1",
            circleId="circle-secret",
            hubUrl=hub_url,
            hubKeyFingerprint=compute_key_fingerprint(hub_key, enc_key),
        )
    )

    cfg = TTSRouterConfig(
        _env_file=None,
        a2a_enabled=True,
        a2a_hub_url=hub_url,
        a2a_hub_key=hub_key,
        a2a_credentials_path=str(creds_file),
        a2a_credentials_encryption_key=enc_key,
        a2a_queue_db_path=str(queue_file),
        a2a_max_tasks_per_minute=1,
        backend_workers=1,
    )
    daemon = A2ABridgeDaemon(config=cfg, store=store, queue=A2AWorkQueue(queue_file))

    seen_auth: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("Authorization", "")
        seen_auth.append(auth)
        if auth == "Bearer tok-v1":
            store.save(
                A2ACredentials(
                    agentId="agent-1",
                    agentToken="tok-v2",
                    circleId="circle-secret",
                    hubUrl=hub_url,
                    hubKeyFingerprint=compute_key_fingerprint(hub_key, enc_key),
                )
            )
            return httpx.Response(401, json={"error": "expired"})
        return httpx.Response(200, json={"status": "QUEUED"})

    limiter = A2ARateLimiter(max_calls=1, window_seconds=60.0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as mock_http:
        client = daemon.get_outbound_client()
        assert client is not None
        client._client = mock_http
        client._external_client = mock_http
        client._rate_limiter = limiter

        # With quota=1 already spent on the initial attempt, 401 credential reload retry must still go out.
        res = await daemon.call_outbound(lambda c: c.send_task("peer-1", "edge-slot"))
        assert res == {"status": "QUEUED"}
        assert seen_auth == ["Bearer tok-v1", "Bearer tok-v2"]

        # Next outbound call must still be blocked by the exhausted 1-slot window.
        with pytest.raises(A2ARateLimitError):
            await daemon.call_outbound(lambda c: c.send_task("peer-1", "second-slot"))


@pytest.mark.asyncio
async def test_concurrent_credential_clear_during_rate_limit_acquire_does_not_fail_inflight_send(
    tmp_path: Path, monkeypatch
):
    monkeypatch.delenv("BACKEND_WORKERS", raising=False)
    creds_file = tmp_path / "creds.json"
    queue_file = tmp_path / "work.db"
    enc_key = "test-secret"
    hub_url = "https://hub.example"
    hub_key = "circle-secret"
    store = A2ACredentialStore(creds_file, enc_key)
    store.save(
        A2ACredentials(
            agentId="agent-1",
            agentToken="tok-live",
            circleId="circle-secret",
            hubUrl=hub_url,
            hubKeyFingerprint=compute_key_fingerprint(hub_key, enc_key),
        )
    )

    cfg = TTSRouterConfig(
        _env_file=None,
        a2a_enabled=True,
        a2a_hub_url=hub_url,
        a2a_hub_key=hub_key,
        a2a_credentials_path=str(creds_file),
        a2a_credentials_encryption_key=enc_key,
        a2a_queue_db_path=str(queue_file),
        backend_workers=4,
    )
    daemon = A2ABridgeDaemon(config=cfg, store=store, queue=A2AWorkQueue(queue_file))

    acquire_entered = asyncio.Event()
    acquire_release = asyncio.Event()

    class BlockingRateLimiter(A2ARateLimiter):
        async def acquire(self, *, skip: bool = False) -> None:
            acquire_entered.set()
            await acquire_release.wait()

    seen_auth: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("Authorization", ""))
        return httpx.Response(200, json={"status": "QUEUED"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as mock_http:
        client = daemon.get_outbound_client()
        assert client is not None
        client._client = mock_http
        client._external_client = mock_http
        client._rate_limiter = BlockingRateLimiter(max_calls=10, window_seconds=60.0)

        inflight = asyncio.create_task(daemon.call_outbound(lambda c: c.send_task("peer-1", "hi")))
        await asyncio.wait_for(acquire_entered.wait(), timeout=2.0)

        # Clear credentials on disk and trigger a concurrent worker request that clears daemon.client.credentials.
        store.clear()
        with pytest.raises(A2ACredentialsUnavailableError):
            await daemon.call_outbound(lambda c: c.list_peers())

        acquire_release.set()
        res = await asyncio.wait_for(inflight, timeout=2.0)
        assert res == {"status": "QUEUED"}
        assert seen_auth == ["Bearer tok-live"]


@pytest.mark.asyncio
async def test_interrupted_reply_reuses_saved_reply_and_task_id_without_re_calling_brain(tmp_path: Path):
    """Item 1: Saving reply_message/reply_task_id before send prevents duplicate Brain calls and preserves task_id on requeue."""
    queue_file = tmp_path / "work.db"
    creds_file = tmp_path / "creds.json"
    store = A2ACredentialStore(creds_file, "test-secret")
    queue = A2AWorkQueue(queue_file)
    cfg = TTSRouterConfig(
        a2a_enabled=True,
        a2a_credentials_path=str(creds_file),
        a2a_queue_db_path=str(queue_file),
    )

    send_started = asyncio.Event()
    send_abort = asyncio.Event()
    sent_task_ids_a: list[str] = []
    sent_task_ids_b: list[str] = []

    async def slow_send_a(**kwargs):
        sent_task_ids_a.append(kwargs["task_id"])
        send_started.set()
        await send_abort.wait()
        return {"status": "QUEUED"}

    client_a = AsyncMock(spec=A2AClient)
    client_a.send_task.side_effect = slow_send_a
    client_b = AsyncMock(spec=A2AClient)
    client_b.send_task.side_effect = lambda **kwargs: sent_task_ids_b.append(kwargs["task_id"]) or {"status": "QUEUED"}

    daemon_a = A2ABridgeDaemon(config=cfg, store=store, queue=queue, client=client_a)
    daemon_b = A2ABridgeDaemon(config=cfg, store=store, queue=queue, client=client_b)

    scope = "test-scope"
    queue.enqueue_event(scope, 1, "inbound-1", "peer-a", "msg-1")
    queue.mark_ack_dispatched(scope, 1)
    event = queue.get_unprocessed_events(scope)[0]

    brain_calls_a = 0

    async def fake_brain_a(*args, **kwargs):
        nonlocal brain_calls_a
        brain_calls_a += 1
        return "Prepared reply once"

    with patch.object(daemon_a, "_query_brain", side_effect=fake_brain_a):
        proc_task = asyncio.create_task(daemon_a._process_queued_event(event))
        await asyncio.wait_for(send_started.wait(), timeout=2.0)

        # Reply metadata must already be persisted in SQLite while send_task is in flight.
        with sqlite3.connect(str(queue_file)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT status, reply_task_id, reply_message FROM a2a_inbox_events WHERE id = ?", (event["id"],)).fetchone()
            assert row["status"] == "PROCESSING"
            assert row["reply_message"] == "Prepared reply once"
            assert row["reply_task_id"] == sent_task_ids_a[0]

        # Simulate leader crash/kill + recovery on daemon_b (requeue + process).
        proc_task.cancel()
        for t in list(daemon_a._inflight_replies):
            t.cancel()
        await asyncio.gather(proc_task, *daemon_a._inflight_replies, return_exceptions=True)

    queue.requeue_processing_events(scope)
    recovered_events = queue.get_unprocessed_events(scope)
    assert len(recovered_events) == 1

    with patch.object(daemon_b, "_query_brain", new_callable=AsyncMock) as brain_b:
        await daemon_b._process_queued_event(recovered_events[0])
        brain_b.assert_not_called()

    assert brain_calls_a == 1
    assert sent_task_ids_b == sent_task_ids_a


@pytest.mark.asyncio
async def test_stop_waits_for_shielded_outbound_reply_before_releasing_lease_and_closing_client(tmp_path: Path):
    """Item 2: stop() must wait for shielded outbound send before releasing lease and closing client."""
    queue_file = tmp_path / "work.db"
    creds_file = tmp_path / "creds.json"
    store = A2ACredentialStore(creds_file, "test-secret")
    queue = A2AWorkQueue(queue_file)
    cfg = TTSRouterConfig(
        a2a_enabled=True,
        a2a_credentials_path=str(creds_file),
        a2a_queue_db_path=str(queue_file),
    )

    events_order: list[str] = []
    send_entered = asyncio.Event()
    allow_send_finish = asyncio.Event()

    async def delayed_send(**kwargs):
        send_entered.set()
        await allow_send_finish.wait()
        events_order.append("send_finished")
        return {"status": "QUEUED"}

    mock_client = AsyncMock(spec=A2AClient)
    mock_client.send_task.side_effect = delayed_send
    mock_client.close.side_effect = lambda: events_order.append("client_closed")

    daemon = A2ABridgeDaemon(config=cfg, store=store, queue=queue, client=mock_client)
    daemon._release_leader_lease = AsyncMock(side_effect=lambda: events_order.append("lease_released"))  # type: ignore[method-assign]
    daemon._running = True
    daemon._is_leader = True

    queue.enqueue_event("test-scope", 1, "t-stop", "peer-a", "hi")
    queue.mark_ack_dispatched("test-scope", 1)
    ev = queue.get_unprocessed_events("test-scope")[0]

    with patch.object(daemon, "_query_brain", new_callable=AsyncMock, return_value="Shutting down reply"):
        proc = asyncio.create_task(daemon._process_queued_event(ev, require_leader=True))
        await asyncio.wait_for(send_entered.wait(), timeout=2.0)

        stop_task = asyncio.create_task(daemon.stop())
        await asyncio.sleep(0.05)
        # Lease must NOT be released and client must NOT be closed while send_task is still in flight.
        assert "lease_released" not in events_order
        assert "client_closed" not in events_order

        allow_send_finish.set()
        await asyncio.wait_for(stop_task, timeout=2.0)
        await asyncio.gather(proc, return_exceptions=True)

    assert events_order == ["send_finished", "lease_released", "client_closed"]
    with sqlite3.connect(str(queue_file)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status FROM a2a_inbox_events WHERE task_id = 't-stop'").fetchone()
        assert row["status"] == "COMPLETED"


def test_requeue_processing_events_marks_expired_retry_window_failed(tmp_path: Path):
    """PROCESSING events past the 10-minute retry deadline finalize to FAILED; recent rows (even >=5 attempts) requeue."""
    q = A2AWorkQueue(tmp_path / "work.db", retry_window_seconds=600.0)
    q.enqueue_event("hub-1", 1, "t-expired", "peer-a", "msg-expired")
    q.mark_ack_dispatched("hub-1", 1)
    ev_id = q.get_unprocessed_events("hub-1")[0]["id"]
    expired_iso = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() - 700.0, tz=timezone.utc).isoformat()
    with sqlite3.connect(str(tmp_path / "work.db")) as conn:
        conn.execute(
            "UPDATE a2a_inbox_events SET status = 'PROCESSING', attempts = 6, first_failed_at = ?, processing_owner = 'w-old' WHERE id = ?",
            (expired_iso, ev_id),
        )
        conn.commit()

    q.enqueue_event("hub-1", 2, "t-retryable", "peer-a", "msg-1")
    q.mark_ack_dispatched("hub-1", 2)
    ev2_id = q.get_unprocessed_events("hub-1")[0]["id"]
    recent_iso = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() - 60.0, tz=timezone.utc).isoformat()
    with sqlite3.connect(str(tmp_path / "work.db")) as conn:
        conn.execute(
            "UPDATE a2a_inbox_events SET status = 'PROCESSING', attempts = 7, first_failed_at = ?, processing_owner = 'w-old' WHERE id = ?",
            (recent_iso, ev2_id),
        )
        conn.commit()

    recovered = q.requeue_processing_events("hub-1")
    assert recovered == 1

    with sqlite3.connect(str(tmp_path / "work.db")) as conn:
        conn.row_factory = sqlite3.Row
        r1 = conn.execute("SELECT status, attempts, processing_owner FROM a2a_inbox_events WHERE id = ?", (ev_id,)).fetchone()
        r2 = conn.execute("SELECT status, attempts, processing_owner FROM a2a_inbox_events WHERE id = ?", (ev2_id,)).fetchone()
        assert r1["status"] == "FAILED" and r1["attempts"] == 6 and r1["processing_owner"] is None
        assert r2["status"] == "ACKNOWLEDGED" and r2["attempts"] == 7 and r2["processing_owner"] is None


def test_revert_and_rate_limit_check_processing_owner(tmp_path: Path):
    """Item 4: Stale worker_id must not revert or modify an event already owned by a new worker."""
    q = A2AWorkQueue(tmp_path / "work.db")
    q.enqueue_event("hub-1", 1, "t-own", "peer-a", "msg")
    q.mark_ack_dispatched("hub-1", 1)
    ev_id = q.get_unprocessed_events("hub-1")[0]["id"]

    assert q.record_processing_start(ev_id, worker_id="worker-old") is True
    # New leader requeues and claims the same event.
    q.requeue_processing_events("hub-1")
    assert q.record_processing_start(ev_id, worker_id="worker-new") is True

    # Late revert/rate-limit from worker-old must be ignored (returns False).
    assert q.revert_processing_start(ev_id, worker_id="worker-old") is False
    assert q.record_rate_limited(ev_id, 5.0, worker_id="worker-old") is False

    with sqlite3.connect(str(tmp_path / "work.db")) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status, attempts, processing_owner FROM a2a_inbox_events WHERE id = ?", (ev_id,)).fetchone()
        assert row["status"] == "PROCESSING"
        assert row["attempts"] == 2
        assert row["processing_owner"] == "worker-new"

    # Current owner can revert cleanly.
    assert q.revert_processing_start(ev_id, worker_id="worker-new") is True


@pytest.mark.asyncio
async def test_reply_path_uses_call_outbound_to_recover_from_401_without_consuming_attempt_or_brain(
    tmp_path: Path, monkeypatch
):
    """Item 5: Reply send goes through call_outbound so 401 reloads credentials without failing or calling Brain twice."""
    monkeypatch.delenv("BACKEND_WORKERS", raising=False)
    creds_file = tmp_path / "creds.json"
    queue_file = tmp_path / "work.db"
    enc_key = "test-secret"
    hub_url = "https://hub.example"
    hub_key = "circle-secret"
    store = A2ACredentialStore(creds_file, enc_key)
    store.save(
        A2ACredentials(
            agentId="agent-1",
            agentToken="tok-stale",
            circleId="circle-secret",
            hubUrl=hub_url,
            hubKeyFingerprint=compute_key_fingerprint(hub_key, enc_key),
        )
    )
    queue = A2AWorkQueue(queue_file)
    cfg = TTSRouterConfig(
        _env_file=None,
        a2a_enabled=True,
        a2a_hub_url=hub_url,
        a2a_hub_key=hub_key,
        a2a_credentials_path=str(creds_file),
        a2a_credentials_encryption_key=enc_key,
        a2a_queue_db_path=str(queue_file),
        backend_workers=1,
    )
    daemon = A2ABridgeDaemon(config=cfg, store=store, queue=queue)

    seen_auth: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("Authorization", "")
        seen_auth.append(auth)
        if auth == "Bearer tok-stale":
            store.save(
                A2ACredentials(
                    agentId="agent-1",
                    agentToken="tok-fresh",
                    circleId="circle-secret",
                    hubUrl=hub_url,
                    hubKeyFingerprint=compute_key_fingerprint(hub_key, enc_key),
                )
            )
            return httpx.Response(401, json={"error": "rotated"})
        return httpx.Response(200, json={"status": "QUEUED"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as mock_http:
        client = daemon.get_outbound_client()
        assert client is not None
        client._client = mock_http
        client._external_client = mock_http

        scope = daemon._hub_scope()
        queue.enqueue_event(scope, 1, "t-401-reply", "peer-a", "hello")
        queue.mark_ack_dispatched(scope, 1)
        ev = queue.get_unprocessed_events(scope)[0]

        with patch.object(daemon, "_query_brain", new_callable=AsyncMock, return_value="Reply after reload") as mock_brain:
            await daemon._process_queued_event(ev)
            mock_brain.assert_awaited_once()

    assert seen_auth == ["Bearer tok-stale", "Bearer tok-fresh"]
    with sqlite3.connect(str(queue_file)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status, attempts FROM a2a_inbox_events WHERE task_id = 't-401-reply'").fetchone()
        assert row["status"] == "COMPLETED"
        assert row["attempts"] == 1


@pytest.mark.asyncio
async def test_spawned_child_task_during_401_retry_does_not_inherit_skip_rate_limit(
    tmp_path: Path, monkeypatch
):
    """Item 6: No ContextVar leakage — tasks spawned inside 401 retry must still enforce rate limits."""
    monkeypatch.delenv("BACKEND_WORKERS", raising=False)
    creds_file = tmp_path / "creds.json"
    queue_file = tmp_path / "work.db"
    enc_key = "test-secret"
    hub_url = "https://hub.example"
    hub_key = "circle-secret"
    store = A2ACredentialStore(creds_file, enc_key)
    store.save(
        A2ACredentials(
            agentId="agent-1",
            agentToken="tok-v1",
            circleId="circle-secret",
            hubUrl=hub_url,
            hubKeyFingerprint=compute_key_fingerprint(hub_key, enc_key),
        )
    )
    cfg = TTSRouterConfig(
        _env_file=None,
        a2a_enabled=True,
        a2a_hub_url=hub_url,
        a2a_hub_key=hub_key,
        a2a_credentials_path=str(creds_file),
        a2a_credentials_encryption_key=enc_key,
        a2a_queue_db_path=str(queue_file),
        a2a_max_tasks_per_minute=1,
        backend_workers=1,
    )
    daemon = A2ABridgeDaemon(config=cfg, store=store, queue=A2AWorkQueue(queue_file))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("Authorization") == "Bearer tok-v1":
            store.save(
                A2ACredentials(
                    agentId="agent-1",
                    agentToken="tok-v2",
                    circleId="circle-secret",
                    hubUrl=hub_url,
                    hubKeyFingerprint=compute_key_fingerprint(hub_key, enc_key),
                )
            )
            return httpx.Response(401, json={"error": "expired"})
        return httpx.Response(200, json={"status": "QUEUED"})

    limiter = A2ARateLimiter(max_calls=1, window_seconds=60.0)
    child_rate_limited = False

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as mock_http:
        client = daemon.get_outbound_client()
        assert client is not None
        client._client = mock_http
        client._external_client = mock_http
        client._rate_limiter = limiter

        async def op(c: A2AClient):
            nonlocal child_rate_limited
            if c.credentials and c.credentials.agent_token == "tok-v2":
                # Spawn a separate asyncio task hitting the daemon while inside the retry callback.
                async def child_call():
                    return await daemon.call_outbound(lambda dc: dc.send_task("peer-1", "child"))

                try:
                    await asyncio.create_task(child_call())
                except A2ARateLimitError:
                    child_rate_limited = True
            return await c.send_task("peer-1", "parent")

        res = await daemon.call_outbound(op)
        assert res == {"status": "QUEUED"}
        assert child_rate_limited is True


@pytest.mark.asyncio
async def test_hub_http_429_and_503_and_401_on_reply_backoff_and_retry(tmp_path: Path, monkeypatch):
    """Round 3 #1: Hub 429 uses Retry-After without attempt; 503/401-after-reload apply exponential backoff."""
    monkeypatch.delenv("BACKEND_WORKERS", raising=False)
    creds_file = tmp_path / "creds.json"
    queue_file = tmp_path / "work.db"
    enc_key = "test-secret"
    hub_url = "https://hub.example"
    hub_key = "circle-secret"
    store = A2ACredentialStore(creds_file, enc_key)
    store.save(
        A2ACredentials(
            agentId="agent-1",
            agentToken="tok-1",
            circleId="circle-secret",
            hubUrl=hub_url,
            hubKeyFingerprint=compute_key_fingerprint(hub_key, enc_key),
        )
    )
    queue = A2AWorkQueue(queue_file)
    cfg = TTSRouterConfig(
        _env_file=None,
        a2a_enabled=True,
        a2a_hub_url=hub_url,
        a2a_hub_key=hub_key,
        a2a_credentials_path=str(creds_file),
        a2a_credentials_encryption_key=enc_key,
        a2a_queue_db_path=str(queue_file),
        backend_workers=1,
    )
    daemon = A2ABridgeDaemon(config=cfg, store=store, queue=queue)

    outcomes = [
        httpx.Response(429, headers={"Retry-After": "3"}, json={"error": "slow down"}),
        httpx.Response(503, json={"error": "upstream down"}),
        httpx.Response(401, json={"error": "expired"}),
        httpx.Response(401, json={"error": "still invalid"}),  # 2nd 401 after reload -> A2ACredentialsUnavailableError
        httpx.Response(200, json={"status": "QUEUED"}),
    ]
    call_idx = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_idx
        resp = outcomes[call_idx]
        call_idx += 1
        return resp

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as mock_http:
        client = daemon.get_outbound_client()
        assert client is not None
        client._client = mock_http
        client._external_client = mock_http

        scope = daemon._hub_scope()
        queue.enqueue_event(scope, 1, "t-hub-err", "peer-a", "hello")
        queue.mark_ack_dispatched(scope, 1)

        with patch.object(daemon, "_query_brain", new_callable=AsyncMock, return_value="Saved reply text") as mock_brain:
            # Attempt 1: Hub 429 -> deferred ~3s (max(Retry-After=3, 2^1)), attempts == 1
            ev = queue.get_unprocessed_events(scope)[0]
            await daemon._process_queued_event(ev)
            with sqlite3.connect(str(queue_file)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT status, attempts, next_retry_at, reply_message FROM a2a_inbox_events WHERE id = ?", (ev["id"],)).fetchone()
                assert row["status"] == "ACKNOWLEDGED"
                assert row["attempts"] == 1
                assert row["reply_message"] == "Saved reply text"
                assert row["next_retry_at"] is not None
                delay = (datetime.fromisoformat(row["next_retry_at"]) - datetime.now(timezone.utc)).total_seconds()
                assert 2.0 <= delay <= 3.5

            # Advance next_retry_at -> Attempt 2: Hub 503 -> attempts == 2, exponential backoff ~4s
            past_iso = datetime.fromtimestamp(0.0, tz=timezone.utc).isoformat()
            with sqlite3.connect(str(queue_file)) as conn:
                conn.execute("UPDATE a2a_inbox_events SET next_retry_at = ? WHERE id = ?", (past_iso, ev["id"]))
                conn.commit()
            ev = queue.get_unprocessed_events(scope)[0]
            await daemon._process_queued_event(ev)
            with sqlite3.connect(str(queue_file)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT status, attempts, next_retry_at FROM a2a_inbox_events WHERE id = ?", (ev["id"],)).fetchone()
                assert row["status"] == "ACKNOWLEDGED"
                assert row["attempts"] == 2
                assert row["next_retry_at"] is not None
                delay_503 = (datetime.fromisoformat(row["next_retry_at"]) - datetime.now(timezone.utc)).total_seconds()
                assert 3.2 <= delay_503 <= 4.5

            # Advance next_retry_at -> Attempt 3: 401 + failed reload retry -> attempts == 3, backoff ~8s
            with sqlite3.connect(str(queue_file)) as conn:
                conn.execute("UPDATE a2a_inbox_events SET next_retry_at = ? WHERE id = ?", (past_iso, ev["id"]))
                conn.commit()
            ev = queue.get_unprocessed_events(scope)[0]
            await daemon._process_queued_event(ev)
            with sqlite3.connect(str(queue_file)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT status, attempts, next_retry_at FROM a2a_inbox_events WHERE id = ?", (ev["id"],)).fetchone()
                assert row["status"] == "ACKNOWLEDGED"
                assert row["attempts"] == 3
                delay_401 = (datetime.fromisoformat(row["next_retry_at"]) - datetime.now(timezone.utc)).total_seconds()
                assert 7.2 <= delay_401 <= 8.5

            # Advance next_retry_at -> Final attempt 200 -> COMPLETED, Brain called only once overall!
            with sqlite3.connect(str(queue_file)) as conn:
                conn.execute("UPDATE a2a_inbox_events SET next_retry_at = ? WHERE id = ?", (past_iso, ev["id"]))
                conn.commit()
            ev = queue.get_unprocessed_events(scope)[0]
            await daemon._process_queued_event(ev)
            mock_brain.assert_awaited_once()

    with sqlite3.connect(str(queue_file)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status, next_retry_at FROM a2a_inbox_events WHERE task_id = 't-hub-err'").fetchone()
        assert row["status"] == "COMPLETED"
        assert row["next_retry_at"] is None


@pytest.mark.asyncio
async def test_unhandled_exception_in_process_queued_event_logs_and_records_failed(tmp_path: Path, caplog):
    """Round 3 #2: General exceptions inside _process_queued_event must log and not leave event stuck in PROCESSING."""
    queue_file = tmp_path / "work.db"
    creds_file = tmp_path / "creds.json"
    store = A2ACredentialStore(creds_file, "test-secret")
    queue = A2AWorkQueue(queue_file)
    cfg = TTSRouterConfig(
        a2a_enabled=True,
        a2a_credentials_path=str(creds_file),
        a2a_queue_db_path=str(queue_file),
    )
    daemon = A2ABridgeDaemon(config=cfg, store=store, queue=queue)
    scope = "test-scope"
    queue.enqueue_event(scope, 1, "t-exc", "peer-a", "boom")
    queue.mark_ack_dispatched(scope, 1)
    ev = queue.get_unprocessed_events(scope)[0]

    with (
        caplog.at_level("ERROR", logger="backend.gateway.a2a_bridge"),
        patch.object(daemon, "_query_brain", side_effect=sqlite3.OperationalError("database is locked")),
    ):
        await daemon._process_queued_event(ev)

    assert any("Unhandled error processing A2A event" in rec.message for rec in caplog.records)
    with sqlite3.connect(str(queue_file)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status, attempts, processing_owner, next_retry_at, error FROM a2a_inbox_events WHERE id = ?", (ev["id"],)).fetchone()
        assert row["status"] == "ACKNOWLEDGED"
        assert row["attempts"] == 1
        assert row["processing_owner"] is None
        assert row["next_retry_at"] is not None
        assert "database is locked" in (row["error"] or "")


@pytest.mark.asyncio
async def test_transient_redis_renewal_timeout_keeps_leader_until_local_lease_expiry(tmp_path: Path, monkeypatch):
    """Round 3 #3: Single Redis renewal timeout retains leadership within local lease margin; abdicates after expiry."""
    monkeypatch.delenv("BACKEND_WORKERS", raising=False)
    store = A2ACredentialStore(tmp_path / "creds.json", "test")
    queue = A2AWorkQueue(tmp_path / "work.db")
    cfg = TTSRouterConfig(
        _env_file=None,
        env="prod",
        backend_workers=4,
        a2a_enabled=True,
        a2a_leader_lease_ttl_seconds=6,
        a2a_credentials_path=str(tmp_path / "creds.json"),
        a2a_queue_db_path=str(tmp_path / "work.db"),
    )
    daemon = A2ABridgeDaemon(config=cfg, store=store, queue=queue)

    class FlakyRedis:
        def __init__(self):
            self.fail_eval = False

        async def set(self, key, value, nx=False, ex=None):
            return True

        async def get(self, key):
            return daemon.worker_id.encode("utf-8")

        async def eval(self, script, numkeys, *args):
            if self.fail_eval:
                raise asyncio.TimeoutError("transient redis blip")
            return 1

    fake_redis = FlakyRedis()
    fake_now = {"t": 1000.0}
    monkeypatch.setattr("app.gateway.a2a_bridge.time.monotonic", lambda: fake_now["t"])

    with patch("app.gateway.a2a_bridge.get_redis", new_callable=AsyncMock, return_value=fake_redis):
        assert await daemon._acquire_leader_lease() is True
        daemon._is_leader = True
        # Lease expires at 1006.0, safety margin is 1.2s -> cutoff at 1004.8
        assert daemon._lease_expires_at == pytest.approx(1006.0)

        # Transient Redis timeout at t=1002.0 -> well inside local grace -> retain leadership
        fake_redis.fail_eval = True
        fake_now["t"] = 1002.0
        assert await daemon._renew_leader_lease() is True
        assert daemon._lease_grace_active is True
        assert daemon.is_leader is True

        # Redis recovers before local deadline -> re-validates lease cleanly
        fake_redis.fail_eval = False
        fake_now["t"] = 1003.0
        assert await daemon._renew_leader_lease() is True
        assert daemon._lease_grace_active is False
        assert daemon._lease_expires_at == pytest.approx(1009.0)

        # Sustained outage past cutoff (1009.0 - 1.2 = 1007.8) -> abdicates cleanly
        fake_redis.fail_eval = True
        fake_now["t"] = 1008.0
        assert await daemon._renew_leader_lease() is False
        assert daemon.is_leader is False


@pytest.mark.asyncio
async def test_renew_leader_lease_set_nx_reacquire_runs_requeue_processing_events(tmp_path: Path, monkeypatch):
    """Round 3 #4: Re-acquiring lease via SET NX in _renew_leader_lease must requeue orphaned PROCESSING rows."""
    monkeypatch.delenv("BACKEND_WORKERS", raising=False)
    queue_file = tmp_path / "work.db"
    store = A2ACredentialStore(tmp_path / "creds.json", "test")
    queue = A2AWorkQueue(queue_file)
    cfg = TTSRouterConfig(
        _env_file=None,
        env="prod",
        backend_workers=4,
        a2a_enabled=True,
        a2a_credentials_path=str(tmp_path / "creds.json"),
        a2a_queue_db_path=str(queue_file),
    )
    daemon = A2ABridgeDaemon(config=cfg, store=store, queue=queue)
    scope = daemon._hub_scope()
    queue.enqueue_event(scope, 1, "t-orphan", "peer-a", "orphaned msg")
    queue.mark_ack_dispatched(scope, 1)
    ev = queue.get_unprocessed_events(scope)[0]
    assert queue.record_processing_start(ev["id"], worker_id="dead-worker") is True

    class ReacquireRedis:
        async def eval(self, script, numkeys, *args):
            return 0  # Expired key -> triggers SET NX fallback

        async def set(self, key, value, nx=False, ex=None):
            return True

    with patch("app.gateway.a2a_bridge.get_redis", new_callable=AsyncMock, return_value=ReacquireRedis()):
        assert await daemon._renew_leader_lease() is True

    recovered = queue.get_unprocessed_events(scope)
    assert len(recovered) == 1
    assert recovered[0]["task_id"] == "t-orphan"
    assert recovered[0]["processing_owner"] is None


@pytest.mark.asyncio
async def test_query_brain_enforces_read_timeout_even_with_shared_sse_http_client(tmp_path: Path):
    """Round 3 #6: _query_brain must enforce per-request read timeout despite infinite SSE client timeout."""
    cfg = TTSRouterConfig(
        _env_file=None,
        a2a_enabled=True,
        a2a_credentials_path=str(tmp_path / "creds.json"),
        a2a_queue_db_path=str(tmp_path / "work.db"),
    )
    daemon = A2ABridgeDaemon(
        config=cfg,
        store=A2ACredentialStore(tmp_path / "creds.json", "test"),
        queue=A2AWorkQueue(tmp_path / "work.db"),
    )
    daemon._brain_timeout_seconds = 0.25

    observed_timeouts: list[httpx.Timeout | None] = []

    class HangingBrainClient:
        is_closed = False

        async def post(self, url, *, json=None, headers=None, timeout=None):
            observed_timeouts.append(timeout)
            read_t = timeout.read if isinstance(timeout, httpx.Timeout) else timeout
            await asyncio.sleep(float(read_t or 5.0))
            raise httpx.ReadTimeout("brain read timed out")

    daemon._http_client = HangingBrainClient()  # type: ignore[assignment]
    res = await asyncio.wait_for(
        daemon._query_brain("hello", requester_id="peer-a", task_id="t-1", context_id="c-1"),
        timeout=1.5,
    )
    assert res is None
    assert len(observed_timeouts) == 1
    assert isinstance(observed_timeouts[0], httpx.Timeout)
    assert observed_timeouts[0].read == pytest.approx(0.25)


@pytest.mark.asyncio
async def test_stop_completes_under_8_seconds_even_when_tasks_and_inflight_hang(tmp_path: Path):
    """Round 3 #7: Worst-case daemon.stop() must finish well below Docker's 10s stop grace (< 8s)."""
    cfg = TTSRouterConfig(
        _env_file=None,
        a2a_enabled=True,
        a2a_credentials_path=str(tmp_path / "creds.json"),
        a2a_queue_db_path=str(tmp_path / "work.db"),
    )
    daemon = A2ABridgeDaemon(
        config=cfg,
        store=A2ACredentialStore(tmp_path / "creds.json", "test"),
        queue=A2AWorkQueue(tmp_path / "work.db"),
    )

    async def stubborn_worker():
        while True:
            try:
                await asyncio.sleep(10.0)
            except asyncio.CancelledError:
                await asyncio.sleep(10.0)

    async def hung_inflight():
        await asyncio.sleep(20.0)

    async def hung_release():
        await asyncio.sleep(10.0)

    daemon._running = True
    daemon._is_leader = True
    daemon._main_task = asyncio.create_task(stubborn_worker())
    daemon._inflight_replies.add(asyncio.create_task(hung_inflight()))
    daemon._release_leader_lease = hung_release  # type: ignore[method-assign]

    started = asyncio.get_running_loop().time()
    await daemon.stop()
    elapsed = asyncio.get_running_loop().time() - started
    assert elapsed < 7.8, f"daemon.stop() took {elapsed:.2f}s (must stay < 8s)"


@pytest.mark.asyncio
async def test_periodic_orphan_sweep_recovers_stuck_processing_after_transient_sqlite_error(tmp_path: Path):
    """Round 4 #1: Orphaned local PROCESSING rows (whose tasks crashed on SQLite error) recover periodically."""
    from app.gateway.a2a_bridge import _parse_retry_after_seconds

    creds_file = tmp_path / "creds.json"
    queue_file = tmp_path / "work.db"
    store = A2ACredentialStore(creds_file, "test-secret")
    queue = A2AWorkQueue(queue_file)
    cfg = TTSRouterConfig(
        _env_file=None,
        a2a_enabled=True,
        a2a_credentials_path=str(creds_file),
        a2a_queue_db_path=str(queue_file),
    )
    mock_client = AsyncMock(spec=A2AClient)
    mock_client.send_task.side_effect = [
        A2ARateLimitError(retry_after=2, max_calls=1),
        {"status": "QUEUED"},
    ]
    daemon = A2ABridgeDaemon(config=cfg, store=store, queue=queue, client=mock_client)
    daemon._orphan_sweep_interval_seconds = 0.01

    scope = daemon._hub_scope()
    queue.enqueue_event(scope, 1, "t-stuck", "peer-a", "stuck msg")
    queue.mark_ack_dispatched(scope, 1)
    queue.enqueue_event(scope, 2, "t-live", "peer-a", "live msg")
    queue.mark_ack_dispatched(scope, 2)
    ev_stuck, ev_live = queue.get_unprocessed_events(scope, limit=10)

    # Mark ev_live as actively owned and tracked in _active_event_ids
    assert queue.record_processing_start(ev_live["id"], worker_id=daemon.worker_id) is True
    daemon._active_event_ids.add(ev_live["id"])

    # Simulate BOTH record_rate_limited AND revert_processing_start failing with sqlite "database is locked"
    with (
        patch.object(daemon, "_query_brain", new_callable=AsyncMock, return_value="reply ok"),
        patch.object(queue, "record_rate_limited", side_effect=sqlite3.OperationalError("database is locked")),
        patch.object(queue, "revert_processing_start", side_effect=sqlite3.OperationalError("database is locked")),
    ):
        await daemon._process_queued_event(ev_stuck)

    # ev_stuck remained PROCESSING in DB, but _active_event_ids no longer holds it
    assert ev_stuck["id"] not in daemon._active_event_ids
    with sqlite3.connect(str(queue_file)) as conn:
        conn.row_factory = sqlite3.Row
        r_stuck = conn.execute("SELECT status, processing_owner FROM a2a_inbox_events WHERE id = ?", (ev_stuck["id"],)).fetchone()
        assert r_stuck["status"] == "PROCESSING"
        assert r_stuck["processing_owner"] == daemon.worker_id

    # Run periodic orphan sweep inside _queue_worker_loop (stopping once recovered event succeeds)
    daemon._running = True
    daemon._is_leader = True
    daemon._last_orphan_sweep = 0.0
    worker = asyncio.create_task(daemon._queue_worker_loop())
    with patch.object(daemon, "_query_brain", new_callable=AsyncMock) as mock_brain:
        for _ in range(40):
            with sqlite3.connect(str(queue_file)) as conn:
                conn.row_factory = sqlite3.Row
                r_stuck = conn.execute("SELECT status FROM a2a_inbox_events WHERE id = ?", (ev_stuck["id"],)).fetchone()
                if r_stuck["status"] == "COMPLETED":
                    break
            await asyncio.sleep(0.05)
        daemon._running = False
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        # Saved reply was reused without re-calling Brain!
        mock_brain.assert_not_called()

    with sqlite3.connect(str(queue_file)) as conn:
        conn.row_factory = sqlite3.Row
        r_stuck = conn.execute("SELECT status FROM a2a_inbox_events WHERE id = ?", (ev_stuck["id"],)).fetchone()
        r_live = conn.execute("SELECT status, processing_owner FROM a2a_inbox_events WHERE id = ?", (ev_live["id"],)).fetchone()
        assert r_stuck["status"] == "COMPLETED"
        assert r_live["status"] == "PROCESSING" and r_live["processing_owner"] == daemon.worker_id
    assert _parse_retry_after_seconds(httpx.Response(429)) == 2.0


@pytest.mark.asyncio
async def test_retry_after_http_date_cap_60s_and_hub_429_respects_local_limiter_with_backoff(
    tmp_path: Path, monkeypatch
):
    """v6 #1/#4: Retry-After supports HTTP-date, caps at 60s, and Hub 429 retries use local rate limiter + backoff."""
    from datetime import timedelta
    from email.utils import format_datetime
    from app.gateway.a2a_bridge import _parse_retry_after_seconds

    assert _parse_retry_after_seconds(httpx.Response(429, headers={"Retry-After": "86400"})) == 60.0
    future_15 = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=15))
    parsed_15 = _parse_retry_after_seconds(httpx.Response(429, headers={"Retry-After": future_15}))
    assert 12.0 <= parsed_15 <= 16.0
    future_far = format_datetime(datetime.now(timezone.utc) + timedelta(hours=3))
    assert _parse_retry_after_seconds(httpx.Response(429, headers={"Retry-After": future_far})) == 60.0

    monkeypatch.delenv("BACKEND_WORKERS", raising=False)
    creds_file = tmp_path / "creds.json"
    queue_file = tmp_path / "work.db"
    enc_key = "test-secret"
    hub_url = "https://hub.example"
    hub_key = "circle-secret"
    store = A2ACredentialStore(creds_file, enc_key)
    store.save(
        A2ACredentials(
            agentId="agent-1",
            agentToken="tok-1",
            circleId="circle-secret",
            hubUrl=hub_url,
            hubKeyFingerprint=compute_key_fingerprint(hub_key, enc_key),
        )
    )
    queue = A2AWorkQueue(queue_file)
    cfg = TTSRouterConfig(
        _env_file=None,
        a2a_enabled=True,
        a2a_hub_url=hub_url,
        a2a_hub_key=hub_key,
        a2a_credentials_path=str(creds_file),
        a2a_credentials_encryption_key=enc_key,
        a2a_queue_db_path=str(queue_file),
        a2a_max_tasks_per_minute=2,
        backend_workers=1,
    )
    daemon = A2ABridgeDaemon(config=cfg, store=store, queue=queue)

    call_n = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_n
        call_n += 1
        if call_n <= 2:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json={"status": "QUEUED"})

    limiter = A2ARateLimiter(max_calls=2, window_seconds=12.0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as mock_http:
        client = daemon.get_outbound_client()
        assert client is not None
        client._client = mock_http
        client._external_client = mock_http
        client._rate_limiter = limiter

        scope = daemon._hub_scope()
        queue.enqueue_event(scope, 1, "t-rl-hub", "peer-a", "hi")
        queue.mark_ack_dispatched(scope, 1)

        past_iso = datetime.fromtimestamp(0.0, tz=timezone.utc).isoformat()
        with patch.object(daemon, "_query_brain", new_callable=AsyncMock, return_value="Reply text"):
            # Attempt 1: consumes local slot 1/2, Hub returns 429 -> attempts=1, backoff ~2s
            ev = queue.get_unprocessed_events(scope)[0]
            await daemon._process_queued_event(ev)
            with sqlite3.connect(str(queue_file)) as conn:
                conn.row_factory = sqlite3.Row
                r1 = conn.execute("SELECT attempts, next_retry_at FROM a2a_inbox_events WHERE id = ?", (ev["id"],)).fetchone()
                assert r1["attempts"] == 1
                d1 = (datetime.fromisoformat(r1["next_retry_at"]) - datetime.now(timezone.utc)).total_seconds()
                assert 1.4 <= d1 <= 2.5

            # Attempt 2: consumes local slot 2/2, Hub returns 429 -> attempts=2, backoff ~4s
            with sqlite3.connect(str(queue_file)) as conn:
                conn.execute("UPDATE a2a_inbox_events SET next_retry_at = ? WHERE id = ?", (past_iso, ev["id"]))
                conn.commit()
            ev = queue.get_unprocessed_events(scope)[0]
            await daemon._process_queued_event(ev)
            with sqlite3.connect(str(queue_file)) as conn:
                conn.row_factory = sqlite3.Row
                r2 = conn.execute("SELECT attempts, next_retry_at FROM a2a_inbox_events WHERE id = ?", (ev["id"],)).fetchone()
                assert r2["attempts"] == 2
                d2 = (datetime.fromisoformat(r2["next_retry_at"]) - datetime.now(timezone.utc)).total_seconds()
                assert 3.4 <= d2 <= 4.5
            assert call_n == 2

            # Attempt 3: local limiter is exhausted, so retry stops BEFORE hitting Hub!
            with sqlite3.connect(str(queue_file)) as conn:
                conn.execute("UPDATE a2a_inbox_events SET next_retry_at = ? WHERE id = ?", (past_iso, ev["id"]))
                conn.commit()
            ev = queue.get_unprocessed_events(scope)[0]
            await daemon._process_queued_event(ev)
            assert call_n == 2  # Local limiter prevented Hub request
            with sqlite3.connect(str(queue_file)) as conn:
                conn.row_factory = sqlite3.Row
                r3 = conn.execute("SELECT attempts, next_retry_at FROM a2a_inbox_events WHERE id = ?", (ev["id"],)).fetchone()
                assert r3["attempts"] == 3
                d3 = (datetime.fromisoformat(r3["next_retry_at"]) - datetime.now(timezone.utc)).total_seconds()
                assert 7.5 <= d3 <= 13.0

            # Once limiter window opens again, attempt 4 succeeds and marks COMPLETED
            limiter._timestamps.clear()
            with sqlite3.connect(str(queue_file)) as conn:
                conn.execute("UPDATE a2a_inbox_events SET next_retry_at = ? WHERE id = ?", (past_iso, ev["id"]))
                conn.commit()
            ev = queue.get_unprocessed_events(scope)[0]
            await daemon._process_queued_event(ev)
            assert call_n == 3
            with sqlite3.connect(str(queue_file)) as conn:
                conn.row_factory = sqlite3.Row
                r4 = conn.execute("SELECT status FROM a2a_inbox_events WHERE id = ?", (ev["id"],)).fetchone()
                assert r4["status"] == "COMPLETED"

        # Local limiter enforces capacity strictly across unrelated calls as well
        res_other = await daemon.call_outbound(lambda c: c.send_task("peer-2", "unrelated task"))
        assert res_other == {"status": "QUEUED"}
        with pytest.raises(A2ARateLimitError):
            await daemon.call_outbound(lambda c: c.send_task("peer-2", "third task"))


@pytest.mark.asyncio
async def test_is_leader_property_and_sse_stop_immediately_on_local_lease_expiry(tmp_path: Path, monkeypatch):
    """Round 4 #4 & #7: Expired local _lease_expires_at flips is_leader False and prevents SSE reconnect spin."""
    monkeypatch.delenv("BACKEND_WORKERS", raising=False)
    store = A2ACredentialStore(tmp_path / "creds.json", "test")
    queue = A2AWorkQueue(tmp_path / "work.db")
    cfg = TTSRouterConfig(
        _env_file=None,
        env="prod",
        backend_workers=4,
        a2a_enabled=True,
        a2a_leader_lease_ttl_seconds=6,
        a2a_credentials_path=str(tmp_path / "creds.json"),
        a2a_queue_db_path=str(tmp_path / "work.db"),
    )
    daemon = A2ABridgeDaemon(config=cfg, store=store, queue=queue)

    now = {"t": 100.0}
    monkeypatch.setattr("app.gateway.a2a_bridge.time.monotonic", lambda: now["t"])

    # Round 4 #7: direct check of local monotonic expiration on is_leader property
    daemon._running = True
    daemon._is_leader = True
    daemon._lease_expires_at = 105.0
    assert daemon.is_leader is True
    now["t"] = 105.1
    assert daemon.is_leader is False

    # Round 4 #4: _run_sse_stream must exit immediately once local lease expired instead of tight reconnect spin
    ensure_calls = 0
    stream_calls = 0

    async def fake_ensure():
        nonlocal ensure_calls
        ensure_calls += 1
        return A2ACredentials(
            agentId="a-1",
            agentToken="t-1",
            circleId="c-1",
            hubUrl="https://hub.example",
            hubKeyFingerprint="fp",
        )

    async def fake_stream(creds):
        nonlocal stream_calls
        stream_calls += 1
        # Simulate local lease expiring while stream is open -> _stream_inbox exits cleanly
        now["t"] = 106.0

    now["t"] = 100.0
    daemon._lease_expires_at = 105.0
    daemon._is_leader = True
    daemon._ensure_credentials = fake_ensure  # type: ignore[method-assign]
    daemon._stream_inbox = fake_stream  # type: ignore[method-assign]

    await asyncio.wait_for(daemon._run_sse_stream(), timeout=1.0)
    assert ensure_calls == 1
    assert stream_calls == 1


@pytest.mark.asyncio
async def test_set_nx_reacquire_preserves_own_active_brain_call_and_requeues_others(tmp_path: Path, monkeypatch):
    """v6 #3: SET NX lease re-acquisition keeps own active Brain call running while requeuing orphaned rows."""
    monkeypatch.delenv("BACKEND_WORKERS", raising=False)
    queue_file = tmp_path / "work.db"
    store = A2ACredentialStore(tmp_path / "creds.json", "test")
    queue = A2AWorkQueue(queue_file)
    cfg = TTSRouterConfig(
        _env_file=None,
        env="prod",
        backend_workers=4,
        a2a_enabled=True,
        a2a_credentials_path=str(tmp_path / "creds.json"),
        a2a_queue_db_path=str(queue_file),
    )
    daemon = A2ABridgeDaemon(config=cfg, store=store, queue=queue)
    scope = daemon._hub_scope()
    queue.enqueue_event(scope, 1, "t-live-nx", "peer-a", "in-flight question")
    queue.enqueue_event(scope, 2, "t-peer-orphan", "peer-a", "dead peer task")
    queue.mark_ack_dispatched(scope, 1)
    queue.mark_ack_dispatched(scope, 2)
    evs = {e["task_id"]: e for e in queue.get_unprocessed_events(scope)}
    ev_live = evs["t-live-nx"]
    ev_peer = evs["t-peer-orphan"]
    assert queue.record_processing_start(ev_peer["id"], worker_id="dead-worker-99") is True

    brain_started = asyncio.Event()
    allow_brain_finish = asyncio.Event()
    brain_calls = 0

    async def slow_brain(*args, **kwargs):
        nonlocal brain_calls
        brain_calls += 1
        brain_started.set()
        await allow_brain_finish.wait()
        return "Single Brain Reply"

    mock_client = AsyncMock()
    mock_client.send_task = AsyncMock(return_value={"status": "QUEUED"})

    class ReacquireRedis:
        async def eval(self, script, numkeys, *args):
            return 0

        async def set(self, key, value, nx=False, ex=None):
            return True

    daemon._running = True
    daemon._is_leader = True
    with (
        patch.object(daemon, "_query_brain", side_effect=slow_brain),
        patch.object(daemon, "call_outbound", new=AsyncMock(return_value={"status": "QUEUED"})),
        patch("app.gateway.a2a_bridge.get_redis", new_callable=AsyncMock, return_value=ReacquireRedis()),
    ):
        proc = asyncio.create_task(daemon._process_queued_event(ev_live, require_leader=True))
        daemon._processing_tasks.add(proc)
        await asyncio.wait_for(brain_started.wait(), timeout=2.0)

        # Simulate SET NX lease re-acquisition while ev_live is mid-Brain call
        assert await asyncio.wait_for(daemon._renew_leader_lease(), timeout=2.0) is True
        assert daemon._pending_requeue is False

        # ev_live must NOT have been cancelled or reverted; dead peer row must be requeued
        assert proc.done() is False
        with sqlite3.connect(str(queue_file)) as conn:
            conn.row_factory = sqlite3.Row
            r_live = conn.execute("SELECT status, processing_owner FROM a2a_inbox_events WHERE id = ?", (ev_live["id"],)).fetchone()
            r_peer = conn.execute("SELECT status, first_failed_at FROM a2a_inbox_events WHERE id = ?", (ev_peer["id"],)).fetchone()
            assert r_live["status"] == "PROCESSING" and r_live["processing_owner"] == daemon.worker_id
            assert r_peer["status"] == "ACKNOWLEDGED" and r_peer["first_failed_at"] is not None

        allow_brain_finish.set()
        await asyncio.wait_for(proc, timeout=2.0)
        assert brain_calls == 1


@pytest.mark.asyncio
async def test_set_nx_reacquire_retries_pending_requeue_after_sqlite_failure(tmp_path: Path, monkeypatch):
    """v6 #5: Transient SQLite error during SET NX requeue leaves _pending_requeue armed and blocks claiming until retry succeeds."""
    monkeypatch.delenv("BACKEND_WORKERS", raising=False)
    queue_file = tmp_path / "work.db"
    store = A2ACredentialStore(tmp_path / "creds.json", "test")
    queue = A2AWorkQueue(queue_file)
    cfg = TTSRouterConfig(
        _env_file=None,
        env="prod",
        backend_workers=4,
        a2a_enabled=True,
        a2a_credentials_path=str(tmp_path / "creds.json"),
        a2a_queue_db_path=str(queue_file),
    )
    daemon = A2ABridgeDaemon(config=cfg, store=store, queue=queue)
    scope = daemon._hub_scope()
    queue.enqueue_event(scope, 1, "t-seq", "peer-a", "new event")
    queue.enqueue_event(scope, 2, "t-stuck-db", "peer-a", "stuck event")
    queue.mark_ack_dispatched(scope, 1)
    queue.mark_ack_dispatched(scope, 2)
    evs = {e["task_id"]: e for e in queue.get_unprocessed_events(scope)}
    ev_new = evs["t-seq"]
    ev_stuck = evs["t-stuck-db"]
    assert queue.record_processing_start(ev_stuck["id"], worker_id="dead-worker") is True

    daemon._running = True
    daemon._is_leader = True

    class ReacquireRedis:
        async def eval(self, script, numkeys, *args):
            return 0

        async def set(self, key, value, nx=False, ex=None):
            return True

    orig_requeue = queue.requeue_processing_events
    calls = 0

    def flaky_requeue(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise sqlite3.OperationalError("database is locked")
        return orig_requeue(*args, **kwargs)

    with (
        patch("app.gateway.a2a_bridge.get_redis", new_callable=AsyncMock, return_value=ReacquireRedis()),
        patch.object(queue, "requeue_processing_events", side_effect=flaky_requeue),
    ):
        # First SET NX attempt fails in SQLite -> _pending_requeue remains True
        assert await asyncio.wait_for(daemon._renew_leader_lease(), timeout=2.0) is True
        assert daemon._pending_requeue is True

        # While requeue is pending, new events must not be claimed
        await daemon._process_queued_event(ev_new, require_leader=True)
        with sqlite3.connect(str(queue_file)) as conn:
            conn.row_factory = sqlite3.Row
            r_new = conn.execute("SELECT status, attempts FROM a2a_inbox_events WHERE id = ?", (ev_new["id"],)).fetchone()
            r_stuck = conn.execute("SELECT status FROM a2a_inbox_events WHERE id = ?", (ev_stuck["id"],)).fetchone()
            assert r_new["status"] == "ACKNOWLEDGED" and r_new["attempts"] == 0
            assert r_stuck["status"] == "PROCESSING"

        # Retry clears _pending_requeue and requeues the stuck row
        assert daemon._run_pending_requeue("retry check") is True
        assert daemon._pending_requeue is False
        with sqlite3.connect(str(queue_file)) as conn:
            conn.row_factory = sqlite3.Row
            r_stuck2 = conn.execute("SELECT status FROM a2a_inbox_events WHERE id = ?", (ev_stuck["id"],)).fetchone()
            assert r_stuck2["status"] == "ACKNOWLEDGED"


@pytest.mark.asyncio
async def test_stop_does_not_block_10s_when_sqlite_database_is_locked(tmp_path: Path):
    """Round 4 #6 & #8: stop() switches SQLite to short busy_timeout and finishes promptly on lock contention."""
    cfg = TTSRouterConfig(
        _env_file=None,
        a2a_enabled=True,
        a2a_brain_timeout_seconds=12.5,
        a2a_credentials_path=str(tmp_path / "creds.json"),
        a2a_queue_db_path=str(tmp_path / "work.db"),
    )
    queue = A2AWorkQueue(tmp_path / "work.db")
    daemon = A2ABridgeDaemon(
        config=cfg,
        store=A2ACredentialStore(tmp_path / "creds.json", "test"),
        queue=queue,
    )
    assert daemon._brain_timeout_seconds == pytest.approx(12.5)

    scope = daemon._hub_scope()
    queue.enqueue_event(scope, 1, "t-lock", "peer-a", "locked")
    queue.mark_ack_dispatched(scope, 1)
    ev = queue.get_unprocessed_events(scope)[0]

    brain_started = asyncio.Event()

    async def waiting_brain(*args, **kwargs):
        brain_started.set()
        await asyncio.sleep(30.0)
        return "never"

    daemon._running = True
    daemon._is_leader = True
    locker = sqlite3.connect(str(tmp_path / "work.db"))
    try:
        with patch.object(daemon, "_query_brain", side_effect=waiting_brain):
            proc = asyncio.create_task(daemon._process_queued_event(ev))
            daemon._processing_tasks.add(proc)
            await asyncio.wait_for(brain_started.wait(), timeout=2.0)

            # Hold exclusive SQLite lock so revert_processing_start contends with DB lock during stop()
            locker.execute("BEGIN EXCLUSIVE")
            started = asyncio.get_running_loop().time()
            await daemon.stop()
            elapsed = asyncio.get_running_loop().time() - started
            assert elapsed < 2.5, f"stop() blocked on locked SQLite for {elapsed:.2f}s"
    finally:
        locker.rollback()
        locker.close()

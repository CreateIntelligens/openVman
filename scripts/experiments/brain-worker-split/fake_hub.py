"""Local /hub/v1 A2A Hub fake for multi-process Backend acceptance testing."""

from __future__ import annotations

import asyncio
from collections import defaultdict
import json
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

app = FastAPI()


class HubState:
    def __init__(self) -> None:
        self.registration_seq = 0
        self.active_agent_id: str | None = None
        self.active_token: str | None = None
        self.stream_generation: int = 0
        self.registrations: list[dict[str, Any]] = []
        self.next_sequence = 0
        self.inbox: list[dict[str, Any]] = []
        self.ack_counts: dict[int, int] = defaultdict(int)
        self.peers_requests = 0
        self.outbound_tasks: list[dict[str, Any]] = []
        self.group_requests = 0
        self.inbound_replies: list[dict[str, Any]] = []
        self.inbound_replies_by_key: dict[str, int] = defaultdict(int)
        self.tokens_seen: list[dict[str, str]] = []
        self.auth_failures: list[dict[str, str]] = []
        self.active_sse_streams = 0
        self.notify_event = asyncio.Event()
        self.hold_replies_after: int | None = None
        self.hold_accept_before_hold: bool = False
        self.held_reply_requests: int = 0
        self.held_reply_task_ids: list[str] = []
        self.reply_release_event = asyncio.Event()
        self.reply_release_event.set()
        self.inbound_reply_task_ids: list[str] = []
        self.accepted_before_hold_by_key: dict[str, str] = {}
        self.replayed_after_hold_by_key: dict[str, list[str]] = defaultdict(list)
        self.reply_error_queues: list[list[dict[str, Any]]] = []
        self.key_error_queue: dict[str, list[dict[str, Any]]] = {}
        self.injected_reply_errors: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def wake_streams(self) -> None:
        self.notify_event.set()
        self.notify_event = asyncio.Event()


state = HubState()


def _require_auth(request: Request, endpoint: str) -> str:
    auth = request.headers.get("Authorization", "")
    agent_id = request.headers.get("X-Agent-ID", "")
    token = auth[len("Bearer "):].strip() if auth.startswith("Bearer ") else ""
    if not state.active_token or token != state.active_token or agent_id != state.active_agent_id:
        state.auth_failures.append({"endpoint": endpoint, "token": token})
        raise HTTPException(status_code=401, detail="Invalid or rotated agent token")
    state.tokens_seen.append({"endpoint": endpoint, "token": token})
    return token


@app.get("/hub/v1/status")
async def hub_status() -> dict[str, Any]:
    return {"status": "ok", "hubId": "synthetic-hub", "mode": "private"}


@app.post("/hub/v1/agents/register")
async def register_agent(request: Request) -> dict[str, Any]:
    body = await request.json()
    state.registration_seq += 1
    agent_id = state.active_agent_id or "openvman-synthetic"
    token = f"tok-{state.registration_seq}-{uuid.uuid4().hex[:12]}"
    state.active_agent_id = agent_id
    state.active_token = token
    state.stream_generation += 1
    record = {
        "seq": state.registration_seq,
        "agentId": agent_id,
        "agentToken": token,
        "displayName": body.get("displayName", "openVman"),
    }
    state.registrations.append(record)
    state.wake_streams()
    return {
        "identity": {
            "hubId": "synthetic-hub",
            "agentId": agent_id,
            "circleId": request.headers.get("X-Hub-Key", "public") or "public",
            "agentToken": token,
            "expiresAt": "2027-01-01T00:00:00Z",
        }
    }


@app.get("/hub/v1/agents")
async def list_peers(request: Request) -> dict[str, Any]:
    _require_auth(request, "peers")
    state.peers_requests += 1
    return {
        "agents": [
            {"agentId": "peer-alpha", "displayName": "Peer Alpha", "state": "ONLINE"},
            {"agentId": "peer-beta", "displayName": "Peer Beta", "state": "ONLINE"},
        ]
    }


@app.post("/hub/v1/agents/{target_agent_id}/tasks")
async def send_task(target_agent_id: str, request: Request) -> dict[str, Any]:
    _require_auth(request, "tasks")
    body = await request.json()
    idem = str(body.get("idempotencyKey") or "")
    record = {
        "targetAgentId": target_agent_id,
        "taskId": body.get("taskId"),
        "contextId": body.get("contextId"),
        "idempotencyKey": idem,
        "message": body.get("message", ""),
    }
    if idem.startswith("reply-"):
        task_id = str(body.get("taskId") or "")
        if idem in state.accepted_before_hold_by_key and state.hold_replies_after is None:
            state.replayed_after_hold_by_key[idem].append(task_id)
            return {"status": "QUEUED", "taskId": task_id, "deduplicated": True}

        if state.hold_replies_after is not None and len(state.inbound_replies) >= state.hold_replies_after:
            state.held_reply_requests += 1
            if task_id:
                state.held_reply_task_ids.append(task_id)
            if state.hold_accept_before_hold and idem not in state.accepted_before_hold_by_key:
                state.accepted_before_hold_by_key[idem] = task_id
                state.inbound_replies.append(record)
                state.inbound_replies_by_key[idem] += 1
                if task_id:
                    state.inbound_reply_task_ids.append(task_id)
            await state.reply_release_event.wait()
            return Response(status_code=499)

        if idem not in state.key_error_queue:
            if state.reply_error_queues:
                state.key_error_queue[idem] = state.reply_error_queues.pop(0)
            else:
                state.key_error_queue[idem] = []
        err_q = state.key_error_queue[idem]
        if err_q:
            fault = err_q.pop(0)
            status_code = int(fault.get("status", 503))
            state.injected_reply_errors[idem].append(
                {"status": status_code, "ts": time.monotonic(), "task_id": task_id}
            )
            if status_code == 401:
                state.auth_failures.append({"endpoint": "tasks", "token": state.active_token or ""})
                if fault.get("rotate", True):
                    state.active_token = None
                    state.stream_generation += 1
                    state.wake_streams()
                raise HTTPException(status_code=401, detail="Injected 401 reply error")
            headers = {}
            if status_code == 429:
                headers["Retry-After"] = str(fault.get("retry_after", 1))
            return Response(
                status_code=status_code,
                headers=headers,
                content=json.dumps({"error": f"Injected HTTP {status_code}"}),
                media_type="application/json",
            )

        state.inbound_replies.append(record)
        state.inbound_replies_by_key[idem] += 1
        if task_id:
            state.inbound_reply_task_ids.append(task_id)
    else:
        state.outbound_tasks.append(record)
    return {"status": "QUEUED", "taskId": body.get("taskId")}


@app.post("/hub/v1/groups/{group_id}/messages")
async def broadcast_group(group_id: str, request: Request) -> dict[str, Any]:
    _require_auth(request, "groups")
    await request.json()
    state.group_requests += 1
    return {"status": "BROADCAST", "groupId": group_id}


@app.post("/hub/v1/agents/{agent_id}/inbox/{sequence}/ack")
async def ack_task(agent_id: str, sequence: int, request: Request) -> Response:
    _require_auth(request, "ack")
    if agent_id != state.active_agent_id:
        raise HTTPException(status_code=404, detail="Unknown agent")
    state.ack_counts[int(sequence)] += 1
    return Response(status_code=204)


@app.get("/hub/v1/agents/{agent_id}/inbox/stream")
async def stream_inbox(agent_id: str, request: Request, afterSequence: int = 0) -> StreamingResponse:
    _require_auth(request, "stream")
    if agent_id != state.active_agent_id:
        raise HTTPException(status_code=404, detail="Unknown agent")

    stream_gen = state.stream_generation
    last_id_hdr = request.headers.get("Last-Event-ID", "").strip()
    cursor = max(int(afterSequence or 0), int(last_id_hdr) if last_id_hdr.isdigit() else 0)

    async def events():
        nonlocal cursor
        state.active_sse_streams += 1
        try:
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                if state.stream_generation != stream_gen:
                    break
                pending = [item for item in state.inbox if item["sequence"] > cursor]
                for item in pending:
                    cursor = item["sequence"]
                    yield f"event: task\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
                if state.stream_generation != stream_gen:
                    break
                ev = state.notify_event
                try:
                    await asyncio.wait_for(ev.wait(), timeout=0.2)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            state.active_sse_streams = max(0, state.active_sse_streams - 1)

    return StreamingResponse(events(), media_type="text/event-stream")


@app.get("/control/state")
async def control_state() -> dict[str, Any]:
    return {
        "registration_seq": state.registration_seq,
        "active_agent_id": state.active_agent_id,
        "active_token": state.active_token,
        "active_sse_streams": state.active_sse_streams,
        "peers_requests": state.peers_requests,
        "outbound_tasks_count": len(state.outbound_tasks),
        "group_requests": state.group_requests,
        "inbox_count": len(state.inbox),
        "ack_counts": {str(k): v for k, v in sorted(state.ack_counts.items())},
        "ack_total": sum(state.ack_counts.values()),
        "inbound_replies_by_key": dict(state.inbound_replies_by_key),
        "inbound_replies_total": len(state.inbound_replies),
        "inbound_reply_task_ids": list(state.inbound_reply_task_ids),
        "held_reply_requests": state.held_reply_requests,
        "held_reply_task_ids": list(state.held_reply_task_ids),
        "accepted_before_hold_by_key": dict(state.accepted_before_hold_by_key),
        "replayed_after_hold_by_key": {k: list(v) for k, v in state.replayed_after_hold_by_key.items()},
        "injected_reply_errors": {k: list(v) for k, v in state.injected_reply_errors.items()},
        "tokens_seen": list(state.tokens_seen),
        "auth_failures": list(state.auth_failures),
    }


@app.post("/control/hold_replies")
async def control_hold_replies(request: Request) -> dict[str, Any]:
    body = await request.json() if (await request.body()) else {}
    state.hold_replies_after = int(body.get("hold_after", 8))
    state.hold_accept_before_hold = bool(body.get("accept_before_hold", False))
    state.held_reply_requests = 0
    state.held_reply_task_ids.clear()
    state.accepted_before_hold_by_key.clear()
    state.replayed_after_hold_by_key.clear()
    state.reply_release_event = asyncio.Event()
    return {
        "holding": True,
        "hold_after": state.hold_replies_after,
        "accept_before_hold": state.hold_accept_before_hold,
    }


@app.post("/control/inject_reply_errors")
async def control_inject_reply_errors(request: Request) -> dict[str, Any]:
    body = await request.json() if (await request.body()) else {}
    queues = body.get("queues", [])
    state.reply_error_queues = [list(q) for q in queues]
    state.key_error_queue.clear()
    state.injected_reply_errors.clear()
    return {"configured_queues": len(state.reply_error_queues)}


@app.post("/control/release_replies")
async def control_release_replies() -> dict[str, Any]:
    state.hold_replies_after = None
    state.hold_accept_before_hold = False
    state.reply_release_event.set()
    return {"released": True}


@app.post("/control/reset")
async def control_reset(request: Request) -> dict[str, Any]:
    body = await request.json() if (await request.body()) else {}
    state.peers_requests = 0
    state.outbound_tasks.clear()
    state.group_requests = 0
    state.tokens_seen.clear()
    state.auth_failures.clear()
    state.hold_replies_after = None
    state.hold_accept_before_hold = False
    state.held_reply_requests = 0
    state.held_reply_task_ids.clear()
    state.reply_error_queues.clear()
    state.key_error_queue.clear()
    state.injected_reply_errors.clear()
    state.reply_release_event.set()
    if body.get("full"):
        state.inbox.clear()
        state.ack_counts.clear()
        state.inbound_replies.clear()
        state.inbound_replies_by_key.clear()
        state.inbound_reply_task_ids.clear()
        state.accepted_before_hold_by_key.clear()
        state.replayed_after_hold_by_key.clear()
    return {"reset": True}


@app.post("/control/push_tasks")
async def control_push_tasks(request: Request) -> dict[str, Any]:
    body = await request.json()
    count = int(body.get("count", 1))
    prefix = str(body.get("prefix", "task"))
    requester = str(body.get("requester", "peer-alpha"))
    pushed = []
    for i in range(count):
        state.next_sequence += 1
        seq = state.next_sequence
        task = {
            "sequence": seq,
            "taskId": f"{prefix}-{seq}-{uuid.uuid4().hex[:8]}",
            "requesterAgentId": requester,
            "contextId": f"ctx-{prefix}-{seq}",
            "message": f"請簡短回覆測試任務 {prefix} #{seq}",
        }
        state.inbox.append(task)
        pushed.append({"sequence": seq, "taskId": task["taskId"]})
    state.wake_streams()
    return {"pushed": pushed, "count": len(pushed)}


@app.post("/control/rotate_token")
async def control_rotate_token() -> dict[str, Any]:
    previous = state.active_token
    state.active_token = None
    state.stream_generation += 1
    state.wake_streams()
    return {"rotated": True, "previous_token": previous}


@app.post("/control/rotate_silent")
async def control_rotate_silent() -> dict[str, Any]:
    """Rotate active token in-place with identical length and without disconnecting SSE."""
    previous = state.active_token or ""
    raw = f"rot-{state.registration_seq}-{uuid.uuid4().hex}{uuid.uuid4().hex}"
    new_token = raw[: len(previous)] if previous else f"tok-rot-{uuid.uuid4().hex[:12]}"
    state.active_token = new_token
    return {
        "rotated_silently": True,
        "previous_token": previous,
        "agentId": state.active_agent_id,
        "agentToken": new_token,
        "circleId": "synthetic-a2a-circle",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8095, access_log=False)

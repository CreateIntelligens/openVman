"""POST /brain/chat/stream: sentences while the model writes, then exactly /chat's payload.

整合方拿第一句就開始 TTS；done 要跟 /chat 一模一樣，斷線、錯誤也要跟 /chat 一樣處理。
"""

from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from core.generation_cancel import is_cancelled, raise_if_cancelled


@pytest.fixture
def chat_route(monkeypatch: pytest.MonkeyPatch):
    from routes import chat as module

    observed: dict[str, Any] = {"events": [], "finalize": [], "stage": [], "failures": []}
    monkeypatch.setattr(
        module, "log_event",
        lambda event, **fields: observed["events"].append((event, fields)),
    )
    monkeypatch.setattr(module, "log_exception", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        module, "record_generation_failure",
        lambda *args: observed["failures"].append(args),
    )
    monkeypatch.setattr(
        module, "_prepare_chat_context",
        lambda request, payload: SimpleNamespace(
            trace_id="trace-1", project_id="default", session_id="s1",
            persona_id="default", request_context={}, turn_decision=None,
        ),
    )

    def finalize(context, reply, tool_steps, response_time_s, *, media=None):
        observed["finalize"].append(reply)
        return {
            "status": "ok", "trace_id": context.trace_id, "session_id": context.session_id,
            "reply": reply, "citations": [], "answer_source": "none",
            "knowledge_searched": bool(tool_steps), "no_answer": False,
            "history": [{"role": "assistant", "content": reply}], "pii_pending": False,
        }

    monkeypatch.setattr(module, "finalize_generation", finalize)
    monkeypatch.setattr(
        module, "stage_turn",
        lambda *args, **kwargs: observed["stage"].append(args) or {"status": "ok", "reply": args[3]},
    )
    monkeypatch.setattr(module, "register_turn", lambda request, payload: None)
    monkeypatch.setattr(module, "reply_media", lambda context, steps: None)
    return module, observed


class _Request:
    def __init__(self, leave_after: float | None = None) -> None:
        self.headers: dict[str, str] = {}
        self.state = SimpleNamespace(trace_id="trace-1")
        self.scope: dict[str, Any] = {}
        self._leave_at = leave_after

    async def is_disconnected(self) -> bool:
        if self._leave_at is None:
            return False
        loop = asyncio.get_running_loop()
        if not hasattr(self, "_start"):
            self._start = loop.time()
        return loop.time() - self._start >= self._leave_at


def _payload(**overrides: Any) -> Any:
    from protocol.schemas import ChatRequest

    return ChatRequest(message="營業時間？", session_id="s1", **overrides)


def _parse(raw: str) -> list[tuple[str, Any]]:
    events = []
    for block in raw.split("\n\n"):
        if not block:
            continue
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        events.append((lines["event"], json.loads(lines["data"])))
    return events


async def _collect(response: Any) -> list[tuple[str, Any]]:
    chunks = [chunk async for chunk in response.body_iterator]
    return _parse("".join(chunks))


_STEPS = [{"name": "search_knowledge", "result": "{}", "round": 0}]
_ANSWER = "營業時間是早上九點。週末休息！歡迎預約"


def _streaming_generation(pieces: list[str], reply: str, steps: list[dict[str, Any]]):
    """Stand-in for execute_generation: a tool round, then the answer streamed in *pieces*."""

    def generate(context, text_listener=None):
        if text_listener is not None:
            text_listener.attempt_started()  # 工具輪：沒有文字
            text_listener.attempt_started()
            for piece in pieces:
                text_listener.text_delta(piece)
        return SimpleNamespace(reply=reply, tool_steps=steps)

    return generate


def test_sentences_then_done_equal_to_chat(chat_route, monkeypatch) -> None:
    module, observed = chat_route
    monkeypatch.setattr(
        module, "execute_generation",
        _streaming_generation(["營業時間是早", "上九點。週末", "休息！歡迎", "預約"], _ANSWER, _STEPS),
    )

    async def run() -> tuple[list[tuple[str, Any]], dict[str, Any]]:
        response = await module.chat_stream(_Request(), _payload())
        assert response.media_type == "text/event-stream"
        assert response.headers["x-accel-buffering"] == "no"
        events = await _collect(response)
        plain = await module.chat(_Request(), _payload())
        return events, plain

    events, plain = asyncio.run(run())

    names = [name for name, _ in events]
    assert names == ["sentence", "sentence", "sentence", "done"]
    sentences = [data for name, data in events if name == "sentence"]
    assert [s["index"] for s in sentences] == [0, 1, 2]
    assert [s["text"] for s in sentences] == ["營業時間是早上九點。", "週末休息！", "歡迎預約"]
    done = events[-1][1]
    assert "".join(s["text"] for s in sentences) == done["reply"]
    for payload in (done, plain):
        assert isinstance(payload.pop("response_time_s"), (int, float))
    assert done == json.loads(json.dumps(plain, ensure_ascii=False))
    assert observed["finalize"] == [_ANSWER, _ANSWER]
    assert [event for event, _ in observed["events"]] == ["chat_complete", "chat_complete"]


def test_first_sentence_arrives_before_generation_finishes(chat_route, monkeypatch) -> None:
    module, _ = chat_route
    release = threading.Event()

    def generate(context, text_listener=None):
        text_listener.attempt_started()
        text_listener.text_delta("第一句。第")
        assert release.wait(5), "the first sentence never reached the client"
        text_listener.text_delta("二句")
        return SimpleNamespace(reply="第一句。第二句", tool_steps=[])

    monkeypatch.setattr(module, "execute_generation", generate)

    async def run() -> list[tuple[str, Any]]:
        response = await module.chat_stream(_Request(), _payload())
        iterator = response.body_iterator
        first = await asyncio.wait_for(iterator.__anext__(), timeout=5)
        release.set()
        rest = [chunk async for chunk in iterator]
        return _parse(first + "".join(rest))

    events = asyncio.run(run())

    assert events[0] == ("sentence", {"index": 0, "text": "第一句。"})
    assert [name for name, _ in events] == ["sentence", "sentence", "done"]


def test_unstreamed_answer_is_still_sent_as_sentences(chat_route, monkeypatch) -> None:
    # 例如 provider 忽略強制工具直接回文字，或工具失敗後的補救回答：沒有 delta 也要有句子。
    module, _ = chat_route
    monkeypatch.setattr(
        module, "execute_generation",
        lambda context, text_listener=None: SimpleNamespace(reply="第一句。第二句", tool_steps=[]),
    )

    events = asyncio.run(_collect_stream(module))

    assert [data["text"] for name, data in events if name == "sentence"] == ["第一句。", "第二句"]
    assert events[-1][0] == "done"


async def _collect_stream(module: Any, request: Any = None, **payload: Any) -> list[tuple[str, Any]]:
    response = await module.chat_stream(request or _Request(), _payload(**payload))
    return await _collect(response)


def test_staged_turn_streams_and_stages_like_chat(chat_route, monkeypatch) -> None:
    module, observed = chat_route
    monkeypatch.setattr(
        module, "execute_generation", _streaming_generation(["答案。"], "答案。", []),
    )

    events = asyncio.run(_collect_stream(module, turn_id="t1", turn_revision=1))

    assert [name for name, _ in events] == ["sentence", "done"]
    assert observed["finalize"] == []
    assert len(observed["stage"]) == 1


def test_generation_failure_ends_with_an_error_event(chat_route, monkeypatch) -> None:
    module, observed = chat_route

    def generate(context, text_listener=None):
        raise RuntimeError("all hops failed")

    monkeypatch.setattr(module, "execute_generation", generate)

    events = asyncio.run(_collect_stream(module))

    [(name, data)] = events
    assert name == "error"
    assert data["status"] == 502
    assert data["detail"]["error_code"] == "LLM_OVERLOAD"
    assert observed["failures"][0][:2] == ("chat_stream", "llm_failure")
    assert observed["finalize"] == []


def test_http_errors_keep_their_status(chat_route, monkeypatch) -> None:
    module, _ = chat_route

    def stale(request, payload):
        raise HTTPException(status_code=409, detail="stale turn revision")

    monkeypatch.setattr(module, "register_turn", stale)

    events = asyncio.run(_collect_stream(module, turn_id="t1", turn_revision=1))

    assert events == [("error", {"status": 409, "detail": "stale turn revision"})]


def _wait_for_cancel(context, text_listener=None):
    text_listener.attempt_started()
    text_listener.text_delta("第一句。第")
    for _ in range(300):
        if is_cancelled():
            break
        threading.Event().wait(0.01)
    raise_if_cancelled("llm_stream", tool_steps=1)
    return SimpleNamespace(reply="不該送出", tool_steps=[])


def test_disconnect_cancels_like_chat(chat_route, monkeypatch) -> None:
    module, observed = chat_route
    monkeypatch.setattr(module, "execute_generation", _wait_for_cancel)

    events = asyncio.run(_collect_stream(module, _Request(leave_after=0.05)))

    assert events == [("sentence", {"index": 0, "text": "第一句。"})]
    assert observed["finalize"] == []
    [(event, fields)] = observed["events"]
    assert event == "chat_cancelled"
    assert fields["stage"] == "llm_stream"


def test_closing_the_stream_stops_generation(chat_route, monkeypatch) -> None:
    # StreamingResponse 在用戶端離開時會關掉 body iterator。
    module, observed = chat_route
    monkeypatch.setattr(module, "execute_generation", _wait_for_cancel)

    async def run() -> str:
        response = await module.chat_stream(_Request(), _payload())
        iterator = response.body_iterator
        first = await asyncio.wait_for(iterator.__anext__(), timeout=5)
        await iterator.aclose()
        for _ in range(300):
            if not module._background_runs:
                break
            await asyncio.sleep(0.01)
        return first

    first = asyncio.run(run())

    assert _parse(first) == [("sentence", {"index": 0, "text": "第一句。"})]
    assert observed["finalize"] == []
    assert [event for event, _ in observed["events"]] == ["chat_cancelled"]


def test_chat_never_passes_a_listener(chat_route, monkeypatch) -> None:
    module, _ = chat_route
    seen: list[dict[str, Any]] = []

    def generate(context, **kwargs):
        seen.append(kwargs)
        return SimpleNamespace(reply="答案。", tool_steps=[])

    monkeypatch.setattr(module, "execute_generation", generate)

    asyncio.run(module.chat(_Request(), _payload()))

    assert seen == [{}]


def test_route_is_served_as_event_stream(chat_route, monkeypatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from safety.internal_auth import require_internal_token

    module, _ = chat_route
    monkeypatch.setattr(
        module, "execute_generation", _streaming_generation(["答案。好"], "答案。好", []),
    )
    app = FastAPI()
    app.include_router(module.router)
    app.dependency_overrides[require_internal_token] = lambda: None

    with TestClient(app) as client:
        response = client.post("/brain/chat/stream", json={"message": "hi", "session_id": "s1"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert [name for name, _ in _parse(response.text)] == ["sentence", "sentence", "done"]

"""/api/v1/chat and /chat/stream carry tts_text, the spoken form of the reply."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import brain_proxy
from app.auth.dependencies import get_current_account
from app.chat_tts_text import annotate_sse, spoken_form


def test_spoken_form_verbalizes_chinese_digits_and_keeps_traditional():
    # markdown 與 emoji 拿掉、電話逐字念；短數字（09:00）留給引擎自己念。
    assert spoken_form("**門診**時間 09:00 至 12:00，電話 0800-123-456 😀") == (
        "門診時間 09:00 至 12:00，電話 零八零零一二三四五六"
    )
    # 英文句不套中文數字讀法。
    assert spoken_form("Call **0800-123-456** now") == "Call 0800-123-456 now"


def test_spoken_form_never_calls_normalize_api(monkeypatch):
    # 正式環境有設 NORMALIZE_API_URL；逐句改寫若退回去打 API，每句同步多等一次遠端
    # 往返（實測 0.4～0.6 秒）還卡住事件迴圈，所以要在有設定的情況下驗證不會打。
    from app.config import get_tts_config

    monkeypatch.setenv("NORMALIZE_API_URL", "http://normalize.invalid/normalize")
    get_tts_config.cache_clear()
    try:
        assert get_tts_config().normalize_api_url == "http://normalize.invalid/normalize"

        def _forbidden(self, *args, **kwargs):
            pytest.fail("spoken_form must not call the normalize API")

        monkeypatch.setattr(httpx.Client, "post", _forbidden)
        monkeypatch.setattr(httpx.AsyncClient, "post", _forbidden)
        assert spoken_form("**門診**時間 09:00 至 12:00，電話 0800-123-456") == (
            "門診時間 09:00 至 12:00，電話 零八零零一二三四五六"
        )
    finally:
        get_tts_config.cache_clear()


def _proxy_app() -> FastAPI:
    app = FastAPI()
    app.include_router(brain_proxy.router)
    app.dependency_overrides[get_current_account] = lambda: None
    return app


def _json_upstream(payload: dict[str, Any]) -> MagicMock:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    upstream = MagicMock()
    upstream.status_code = 200
    upstream.headers = {"content-type": "application/json", "content-length": str(len(body))}
    upstream.aread = AsyncMock(return_value=body)
    upstream.aclose = AsyncMock(return_value=None)
    client = MagicMock()
    client.build_request = MagicMock(side_effect=lambda **kwargs: kwargs)
    client.send = AsyncMock(return_value=upstream)
    return client


def test_chat_reply_gains_tts_text():
    client = _json_upstream({"reply": "請撥 **0800-123-456** 洽詢。", "citations": []})
    cfg = MagicMock(
        brain_url="http://brain:8100", gateway_internal_token="t",
        brain_proxy_max_body_bytes=110 * 1024 * 1024,
    )
    with (
        patch("app.brain_proxy.get_tts_config", return_value=cfg),
        patch("app.brain_proxy._http.get", return_value=client),
    ):
        response = TestClient(_proxy_app()).post("/api/v1/chat", json={"message": "hi"})
    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "請撥 **0800-123-456** 洽詢。"
    assert body["tts_text"] == "請撥 零八零零一二三四五六 洽詢。"
    assert int(response.headers["content-length"]) == len(response.content)


def test_non_chat_json_is_left_alone():
    client = _json_upstream({"reply": "x", "personas": []})
    cfg = MagicMock(
        brain_url="http://brain:8100", gateway_internal_token="t",
        brain_proxy_max_body_bytes=110 * 1024 * 1024,
    )
    with (
        patch("app.brain_proxy.get_tts_config", return_value=cfg),
        patch("app.brain_proxy._http.get", return_value=client),
    ):
        response = TestClient(_proxy_app()).get("/api/v1/personas")
    assert "tts_text" not in response.json()


def test_sse_sentence_and_done_events_gain_tts_text():
    async def run() -> list[bytes]:
        async def events():
            yield b'event: sentence\ndata: {"index": 0, "text": "\xe7\xac\xac1\xe5\x8f\xa5\xe3\x80\x82"}\n\n'
            # 一個事件分兩個 chunk 到：要等收齊才改寫。
            yield b'event: sentence\ndata: {"index": 1, "te'
            yield b'xt": "**\xe7\xac\xac2\xe5\x8f\xa5**"}\n\nevent: done\ndata: {"reply": "\xe7\xac\xac1\xe5\x8f\xa5\xe3\x80\x82\xe7\xac\xac2\xe5\x8f\xa5", "no_answer": false}\n\n'
            yield b'event: server_error\ndata: {"message": "x"}\n\n'

        return [chunk async for chunk in annotate_sse(events())]

    chunks = asyncio.run(run())
    parsed = []
    for chunk in chunks:
        lines = chunk.rstrip(b"\n").split(b"\n")
        event = [l for l in lines if l.startswith(b"event:")][0][6:].strip().decode()
        data = json.loads(b"".join(l[5:].strip() for l in lines if l.startswith(b"data:")))
        parsed.append((event, data))
    assert parsed[0] == ("sentence", {"index": 0, "text": "第1句。", "tts_text": "第1句。"})
    assert parsed[1] == ("sentence", {"index": 1, "text": "**第2句**", "tts_text": "第2句"})
    assert parsed[2][0] == "done"
    assert parsed[2][1]["tts_text"] == "第1句。第2句"
    assert parsed[2][1]["no_answer"] is False
    assert parsed[3] == ("server_error", {"message": "x"})

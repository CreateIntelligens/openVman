"""Tests for TTS text preparation, normalization API, and fallback regex pipeline."""

from __future__ import annotations

import httpx
import pytest

from app.tts_text import (
    clean_for_tts,
    digits_to_chinese,
    prepare_tts_text,
    prepare_tts_text_async,
)


def test_clean_for_tts_strips_markdown_and_emoji():
    raw = "**重要**：請造訪 [官網](https://example.com)！\n# 標題 1\n`code` 😊🎉"
    cleaned = clean_for_tts(raw)
    assert "重要" in cleaned
    assert "官網" in cleaned
    assert "https://example.com" not in cleaned
    assert "#" not in cleaned
    assert "😊" not in cleaned
    assert "🎉" not in cleaned


def test_digits_to_chinese_converts_numbers_and_dates():
    assert "一百六十二" in digits_to_chinese("省下 162 萬元")
    assert "二零三零年" in digits_to_chinese("2030年達成目標")
    assert "零二一二三四五六七八" in digits_to_chinese("電話：02-1234-5678")
    assert "一一九" in digits_to_chinese("請撥打 119 求助")
    assert "三點一四" in digits_to_chinese("圓周率是 3.14")


def test_prepare_tts_text_local_fallback():
    raw = "**三立**在 2030年 預計省下 162 萬元！"
    prepared = prepare_tts_text(raw, normalize_url="", simplified=False)
    assert "**" not in prepared
    assert "二零三零年" in prepared
    assert "一百六十二" in prepared


def test_prepare_tts_text_with_mock_api(monkeypatch):
    def mock_post(url, json=None, timeout=None):
        request = httpx.Request("POST", url, json=json)
        return httpx.Response(
            200,
            json={
                "raw_text": json.get("text"),
                "norm_text": "三立在二零三零年預計省下一百六十二萬元",
                "simplified": "三立在二零三零年预计省下一百六十二万元",
            },
            request=request,
        )

    monkeypatch.setattr(httpx.Client, "post", lambda self, url, **kwargs: mock_post(url, **kwargs))

    res = prepare_tts_text("三立在 2030年 預計省下 162 萬元", normalize_url="http://fake-api/normalize")
    assert res == "三立在二零三零年预计省下一百六十二万元"


@pytest.mark.asyncio
async def test_prepare_tts_text_async_with_mock_api(monkeypatch):
    async def mock_async_post(self, url, json=None, timeout=None, **kwargs):
        request = httpx.Request("POST", url, json=json)
        return httpx.Response(
            200,
            json={
                "raw_text": json.get("text"),
                "norm_text": "三立在二零三零年預計省下一百六十二萬元",
                "simplified": "三立在二零三零年预计省下一百六十二万元",
            },
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_async_post)

    res = await prepare_tts_text_async("三立在 2030年 預計省下 162 萬元", normalize_url="http://fake-api/normalize")
    assert res == "三立在二零三零年预计省下一百六十二万元"


def test_prepare_tts_text_api_error_fallback(monkeypatch):
    def mock_post_err(self, url, **kwargs):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(httpx.Client, "post", mock_post_err)

    res = prepare_tts_text("2030年省下 162 萬元", normalize_url="http://broken-api/normalize", simplified=False)
    assert "二零三零年" in res
    assert "一百六十二" in res

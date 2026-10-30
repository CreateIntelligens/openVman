"""Borrow the Taiwanese word tables without invoking upstream synthesis."""

from __future__ import annotations

import asyncio

import httpx

from app.config import TTSRouterConfig

#: 詞表查詢實測中位數 25 ms、最慢 44 ms；查不到就讓這一站失敗換下一家，
#: 不能讓一個查表把整句 TTS 卡住數秒。
DEFAULT_HANJI_TIMEOUT_SECONDS = 0.8


class HanjiConverter:
    """Convert independently for each engine so fallback keeps its source text."""

    def __init__(self, config: TTSRouterConfig) -> None:
        self.url = getattr(
            config, "effective_tts_hanji_convert_url",
            getattr(config, "tts_hanji_convert_url", ""),
        ).strip()
        value = getattr(config, "tts_hanji_timeout_seconds", None)
        self.timeout = (
            float(value) if isinstance(value, (int, float)) and value > 0
            else DEFAULT_HANJI_TIMEOUT_SECONDS
        )

    @staticmethod
    def _result(response: httpx.Response, version: str) -> str:
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError("Invalid Taiwanese word table response") from exc
        if (
            not isinstance(data, dict)
            or data.get("version") != version
            or not isinstance(data.get("converted"), str)
            or not data["converted"].strip()
        ):
            raise RuntimeError("Invalid Taiwanese word table response")
        return data["converted"]

    def convert(self, text: str, version: str) -> str:
        if not self.url:
            return text
        # 同步路徑沒有外層牆鐘：每個階段各 timeout 秒，實際最壞約兩倍。
        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(
                self.url,
                params={"text": text, "version": version, "log_unknown": "false"},
            )
        return self._result(response, version)

    async def convert_async(self, text: str, version: str) -> str:
        if not self.url:
            return text
        try:
            async with asyncio.timeout(self.timeout), httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    self.url,
                    params={"text": text, "version": version, "log_unknown": "false"},
                )
        except TimeoutError as exc:
            # 呼叫端只認 httpx.HTTPError／RuntimeError，換成 httpx 的逾時。
            raise httpx.TimeoutException(
                f"word table timed out after {self.timeout:.1f}s",
            ) from exc
        return self._result(response, version)

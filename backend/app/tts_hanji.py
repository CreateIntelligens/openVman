"""Borrow the Taiwanese word tables without invoking upstream synthesis."""

from __future__ import annotations

import httpx

from app.config import TTSRouterConfig


class HanjiConverter:
    """Convert independently for each engine so fallback keeps its source text."""

    def __init__(self, config: TTSRouterConfig) -> None:
        self.url = getattr(
            config, "effective_tts_hanji_convert_url",
            getattr(config, "tts_hanji_convert_url", ""),
        ).strip()

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
        with httpx.Client(timeout=3.0) as client:
            response = client.get(
                self.url,
                params={"text": text, "version": version, "log_unknown": "false"},
            )
        return self._result(response, version)

    async def convert_async(self, text: str, version: str) -> str:
        if not self.url:
            return text
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(
                self.url,
                params={"text": text, "version": version, "log_unknown": "false"},
            )
        return self._result(response, version)

"""Use a project's Gemini key directly; the shared TTS console owns its key."""

from __future__ import annotations

import base64
import io
import json
import wave
from collections.abc import AsyncIterator
from time import monotonic

import httpx

from app.providers.base import NormalizedTTSResult, SynthesizeRequest

GOOGLE_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
SAMPLE_RATE = 24000


def request_payload(request: SynthesizeRequest) -> dict:
    return {
        "contents": [{"role": "user", "parts": [{"text": request.text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "responseFormat": {
                "audio": {"mimeType": "AUDIO_L16", "sampleRate": SAMPLE_RATE},
            },
            "speechConfig": {
                "voiceConfig": {"voice": request.voice_hint or "Kore"},
            },
        },
    }


def audio_chunks(payload: dict) -> list[bytes]:
    chunks = []
    for candidate in payload.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data") or {}
            if inline.get("data"):
                mime = inline.get("mimeType", inline.get("mime_type", ""))
                if not mime.lower().startswith(("audio/pcm", "audio/l16")):
                    raise RuntimeError("Gemini TTS returned an unexpected audio format")
                chunks.append(base64.b64decode(inline["data"], validate=True))
    return chunks


def event_chunks(data: str) -> list[bytes]:
    try:
        payload = json.loads(data)
    except ValueError:
        raise RuntimeError("Project Gemini TTS stream failed") from None
    if not isinstance(payload, dict) or "error" in payload:
        raise RuntimeError("Project Gemini TTS stream failed")
    return audio_chunks(payload)


def synthesize(
    request: SynthesizeRequest, credential, model: str, client: httpx.Client,
) -> NormalizedTTSResult:
    started = monotonic()
    try:
        response = client.post(
            f"{GOOGLE_API_BASE}/{model}:generateContent",
            headers={"x-goog-api-key": credential.api_key},
            json=request_payload(request),
        )
    except httpx.HTTPError:
        # 傳輸錯誤的訊息與 traceback 可能帶出請求內容；from None 斷開鏈結，金鑰不進 log。
        raise RuntimeError("Project Gemini TTS request failed") from None
    if response.status_code >= 400:
        raise RuntimeError(
            f"Project Gemini TTS failed (HTTP {response.status_code})",
        )
    pcm = b"".join(audio_chunks(response.json()))
    if not pcm:
        raise RuntimeError("Project Gemini TTS returned no audio")
    wav = io.BytesIO()
    with wave.open(wav, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(pcm)
    return NormalizedTTSResult(
        audio_bytes=wav.getvalue(), content_type="audio/wav",
        sample_rate=SAMPLE_RATE, provider="gemini-tts",
        route_kind="provider", route_target="gemini-tts",
        latency_ms=round((monotonic() - started) * 1000, 2),
        raw_metadata={
            "credential_id": credential.credential_id,
            "credential_source": credential.source,
            "model": model,
        },
    )


class _ProjectGeminiStream:
    """Yield the primed first chunk, then the rest; any end path releases upstream.

    不用 async generator 包：還沒開始迭代就 aclose() 的 generator 不會跑 finally，
    上游連線與 client 會留著不關。
    """

    def __init__(self, first: bytes, chunks, response, client) -> None:
        self._first: bytes | None = first
        self._chunks = chunks
        self._response = response
        self._client = client
        self._closed = False

    def __aiter__(self) -> _ProjectGeminiStream:
        return self

    async def __anext__(self) -> bytes:
        if self._closed:
            raise StopAsyncIteration
        if self._first is not None:
            first, self._first = self._first, None
            return first
        try:
            return await anext(self._chunks)
        except BaseException:
            await self.aclose()
            raise

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._chunks.aclose()
        finally:
            try:
                await self._response.aclose()
            finally:
                await self._client.aclose()


async def open_stream(
    request: SynthesizeRequest, credential, model: str,
) -> AsyncIterator[bytes]:
    client = httpx.AsyncClient(timeout=60.0)
    response = None
    chunks = None
    try:
        upstream = client.build_request(
            "POST", f"{GOOGLE_API_BASE}/{model}:streamGenerateContent?alt=sse",
            headers={"x-goog-api-key": credential.api_key},
            json=request_payload(request),
        )
        try:
            response = await client.send(upstream, stream=True)
        except httpx.HTTPError:
            raise RuntimeError("Project Gemini TTS request failed") from None
        if response.status_code >= 400:
            raise RuntimeError(
                f"Project Gemini TTS failed (HTTP {response.status_code})",
            )

        async def audio() -> AsyncIterator[bytes]:
            event: list[str] = []
            try:
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        event.append(line[5:].lstrip())
                    elif not line and event:
                        data = "\n".join(event)
                        event.clear()
                        if data == "[DONE]":
                            return
                        for chunk in event_chunks(data):
                            yield chunk
            except httpx.HTTPError:
                raise RuntimeError("Project Gemini TTS stream failed") from None
            if event and "\n".join(event) != "[DONE]":
                for chunk in event_chunks("\n".join(event)):
                    yield chunk

        chunks = audio()
        first = await anext(chunks, None)
        if not first:
            raise RuntimeError("Project Gemini TTS returned no audio")
    except BaseException:
        if chunks is not None:
            await chunks.aclose()
        if response is not None:
            await response.aclose()
        await client.aclose()
        raise

    return _ProjectGeminiStream(first, chunks, response, client)

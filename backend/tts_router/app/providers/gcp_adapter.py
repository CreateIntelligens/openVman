"""Google Cloud TTS adapter for TTS routing."""

from __future__ import annotations

from time import monotonic
from typing import Any

from app.config import TTSRouterConfig
from app.providers.base import NormalizedTTSResult, SynthesizeRequest


# GCP audio encoding name -> content_type
_ENCODING_CONTENT_TYPE = {
    "LINEAR16": "audio/l16",
    "MP3": "audio/mpeg",
    "OGG_OPUS": "audio/ogg",
}


class GCPTTSAdapter:
    """Synthesize speech via Google Cloud TTS and return a NormalizedTTSResult."""

    def __init__(self, config: TTSRouterConfig) -> None:
        self._config = config
        self._client: Any = None

    @property
    def provider_name(self) -> str:
        return "gcp"

    @property
    def enabled(self) -> bool:
        return self._config.tts_gcp_enabled

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        from google.cloud import texttospeech

        self._client = texttospeech.TextToSpeechClient()
        return self._client

    def synthesize(self, request: SynthesizeRequest) -> NormalizedTTSResult:
        """Call Google Cloud TTS and return normalized result."""
        from google.cloud import texttospeech

        t0 = monotonic()
        client = self._get_client()

        voice_name = request.voice_hint or self._config.tts_gcp_voice_name
        sample_rate = request.sample_rate or self._config.tts_gcp_sample_rate
        encoding_name = self._config.tts_gcp_audio_encoding

        synthesis_input = texttospeech.SynthesisInput(text=request.text)
        voice_params = texttospeech.VoiceSelectionParams(
            language_code=_locale_to_gcp_language(request.locale),
            name=voice_name,
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=getattr(texttospeech.AudioEncoding, encoding_name, texttospeech.AudioEncoding.LINEAR16),
            sample_rate_hertz=sample_rate,
        )

        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice_params,
            audio_config=audio_config,
        )

        latency_ms = (monotonic() - t0) * 1000
        content_type = _ENCODING_CONTENT_TYPE.get(encoding_name, "audio/l16")

        return NormalizedTTSResult(
            audio_bytes=response.audio_content,
            content_type=content_type,
            sample_rate=sample_rate,
            provider="gcp",
            route_kind="provider",
            route_target="gcp-tts",
            latency_ms=latency_ms,
            raw_metadata={
                "voice_name": voice_name,
                "encoding": encoding_name,
            },
        )


_LOCALE_TO_GCP_LANGUAGE: dict[str, str] = {
    "zh-TW": "cmn-TW",
    "zh-CN": "cmn-CN",
    "en-US": "en-US",
    "ja-JP": "ja-JP",
}


def _locale_to_gcp_language(locale: str) -> str:
    """Map locale to GCP language code."""
    return _LOCALE_TO_GCP_LANGUAGE.get(locale, "cmn-TW")

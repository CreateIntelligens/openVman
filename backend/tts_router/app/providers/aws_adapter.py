"""AWS Polly adapter for TTS routing."""

from __future__ import annotations

from time import monotonic
from typing import Any

from app.config import TTSRouterConfig
from app.providers.base import NormalizedTTSResult, SynthesizeRequest


class AWSPollyAdapter:
    """Synthesize speech via AWS Polly and return a NormalizedTTSResult."""

    def __init__(self, config: TTSRouterConfig) -> None:
        self._config = config
        self._client: Any = None

    @property
    def provider_name(self) -> str:
        return "aws"

    @property
    def enabled(self) -> bool:
        return self._config.tts_aws_enabled

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        import boto3

        self._client = boto3.client(
            "polly",
            region_name=self._config.tts_aws_region,
            aws_access_key_id=self._config.tts_aws_access_key_id or None,
            aws_secret_access_key=self._config.tts_aws_secret_access_key or None,
        )
        return self._client

    def synthesize(self, request: SynthesizeRequest) -> NormalizedTTSResult:
        """Call Polly and return normalized result.

        Raises on failure — the caller (router service) catches and classifies.
        """
        t0 = monotonic()
        client = self._get_client()

        voice_id = request.voice_hint or self._config.tts_aws_polly_voice_id
        sample_rate = str(request.sample_rate or self._config.tts_aws_sample_rate)

        response = client.synthesize_speech(
            Text=request.text,
            VoiceId=voice_id,
            Engine=self._config.tts_aws_polly_engine,
            OutputFormat=self._config.tts_aws_output_format,
            SampleRate=sample_rate,
            LanguageCode=_locale_to_language_code(request.locale),
        )

        audio_stream = response["AudioStream"]
        audio_bytes = audio_stream.read()
        latency_ms = (monotonic() - t0) * 1000

        content_type = response.get("ContentType", "audio/pcm")

        return NormalizedTTSResult(
            audio_bytes=audio_bytes,
            content_type=content_type,
            sample_rate=int(sample_rate),
            provider="aws",
            route_kind="provider",
            route_target="aws-polly",
            latency_ms=latency_ms,
            raw_metadata={
                "voice_id": voice_id,
                "engine": self._config.tts_aws_polly_engine,
                "request_characters": response.get("RequestCharacters", len(request.text)),
            },
        )


_LOCALE_TO_LANGUAGE_CODE: dict[str, str] = {
    "zh-TW": "cmn-CN",  # Polly uses cmn-CN for Mandarin
    "zh-CN": "cmn-CN",
    "en-US": "en-US",
    "ja-JP": "ja-JP",
}


def _locale_to_language_code(locale: str) -> str:
    """Map a locale hint to an AWS Polly LanguageCode."""
    return _LOCALE_TO_LANGUAGE_CODE.get(locale, "cmn-CN")

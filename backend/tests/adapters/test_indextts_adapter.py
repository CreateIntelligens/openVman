from __future__ import annotations

from unittest.mock import MagicMock

import httpx

from app.config import TTSRouterConfig
from app.providers.base import SynthesizeRequest
from app.providers.indextts_adapter import IndexTTSAdapter


def test_synthesize_sends_internal_token() -> None:
    config = TTSRouterConfig(
        tts_indextts_url="http://index-tts-vllm:8011",
        tts_indextts_default_character="hayley",
        gateway_internal_token="test-internal-token",
    )
    adapter = IndexTTSAdapter(config)
    adapter._opencc_t2s = None
    response = httpx.Response(
        200,
        content=b"wav",
        headers={"content-type": "audio/wav"},
    )
    adapter._client.post = MagicMock(return_value=response)

    adapter.synthesize(SynthesizeRequest(text="你好", voice_hint="jay"))

    adapter._client.post.assert_called_once_with(
        "http://index-tts-vllm:8011/tts",
        json={"text": "你好", "character": "jay"},
        headers={"X-Internal-Token": "test-internal-token"},
    )

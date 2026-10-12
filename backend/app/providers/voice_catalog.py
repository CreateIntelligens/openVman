"""Voice lists and the admin provider menu, adapted from each TTS provider.

Each provider publishes its voices in its own shape; this module turns them
into plain voice ids (plus labels where the provider has them) for the admin
provider menu and the resource registry.
"""

from __future__ import annotations

import logging
from typing import Any

from app.http_client import SharedAsyncClient
from app.providers.cosyvoice_adapter import (
    COSYVOICE_DEFAULT_VOICE,
    COSYVOICE_PROVIDER_NAME,
)
from app.providers.gemini_tts_adapter import GEMINI_DEFAULT_VOICE, GEMINI_PROVIDER_NAME
from app.providers.voxcpm_adapter import VOXCPM_DEFAULT_VOICE, VOXCPM_PROVIDER_NAME

logger = logging.getLogger("backend")

TTS_PROVIDER_TIMEOUT_SECONDS = 5
_INTERNAL_TOKEN_HEADER = "X-Internal-Token"

PROVIDER_NAMES = {
    "aws": "AWS Polly",
    "aws-polly": "AWS Polly",
    "edge-tts": "Edge TTS",
    "gcp": "GCP TTS",
    "gcp-tts": "GCP TTS",
    GEMINI_PROVIDER_NAME: "Gemini TTS",
    "indextts": "IndexTTS",
    VOXCPM_PROVIDER_NAME: "VoxCPM",
    COSYVOICE_PROVIDER_NAME: "CosyVoice",
}

EDGE_TTS_VOICES = (
    "zh-TW-HsiaoChenNeural",
    "zh-TW-YunJheNeural",
    "zh-CN-XiaoyiNeural",
)

EDGE_TTS_VOICE_LABELS = {
    "zh-TW-HsiaoChenNeural": "曉臻 (Edge-TTS)",
    "zh-TW-YunJheNeural": "雲哲 (Edge-TTS)",
    "zh-CN-XiaoyiNeural": "曉伊 (Edge-TTS)",
}


async def fetch_provider_voices(
    http: SharedAsyncClient,
    base_url: str,
    voices_path: str,
    provider_name: str,
    *,
    headers: dict[str, str] | None = None,
) -> list[str]:
    voices_url = f"{base_url.rstrip('/')}{voices_path}"
    try:
        if headers is None:
            response = await http.get().get(
                voices_url,
                timeout=TTS_PROVIDER_TIMEOUT_SECONDS,
                follow_redirects=True,
            )
        else:
            response = await http.get().get(
                voices_url,
                timeout=TTS_PROVIDER_TIMEOUT_SECONDS,
                headers=headers,
                follow_redirects=True,
            )
        response.raise_for_status()
        return extract_voice_names(response.json())
    except Exception as exc:
        logger.warning("failed to fetch %s voices from %s: %s", provider_name, voices_url, exc)
        return []


async def fetch_indextts_voices(
    http: SharedAsyncClient,
    base_url: str,
    internal_token: str,
) -> list[str]:
    return await fetch_provider_voices(
        http,
        base_url,
        "/audio/voices",
        "indextts",
        headers={_INTERNAL_TOKEN_HEADER: internal_token},
    )


async def fetch_gemini_voices(http: SharedAsyncClient, base_url: str) -> list[str]:
    return await fetch_provider_voices(http, base_url, "/api/voices", "gemini")


def excluded_voices(cfg: Any, config_attr: str) -> frozenset[str]:
    """voice_id 黑名單：上游清單不是我們維護的，這裡濾掉不想露出的聲音。"""
    raw = getattr(cfg, config_attr, "") or ""
    return frozenset(item.strip() for item in raw.split(",") if item.strip())


async def fetch_castvoice_voices(
    http: SharedAsyncClient,
    voices_url: str,
    provider: str,
    excluded: frozenset[str],
    *,
    headers: dict[str, str] | None = None,
) -> list[tuple[str, str]]:
    """回傳 CastAgent 相容 /voices 端點的 ``(voice_id, label)`` 清單。

    這類端點用 ``voice_id``＋中文 ``label``，與其他 provider 的 ``name`` 欄位
    不同，故不走 extract_voice_names；label 留下來給 admin 選單。
    """
    # headers 只在有值時才傳：VoxCPM360 的 /voices 不需要驗證，多送一個空
    # dict 只是噪音。
    extra = {"headers": headers} if headers else {}
    try:
        response = await http.get().get(
            voices_url,
            timeout=TTS_PROVIDER_TIMEOUT_SECONDS,
            follow_redirects=True,
            **extra,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        logger.warning(
            "failed to fetch %s voices from %s: %s", provider, voices_url, exc,
        )
        return []

    voice_entries = payload.get("voices") if isinstance(payload, dict) else None
    if not isinstance(voice_entries, list):
        return []

    voices: list[tuple[str, str]] = []
    for entry in voice_entries:
        if not isinstance(entry, dict):
            continue
        voice_id = entry.get("voice_id")
        if not isinstance(voice_id, str) or not voice_id:
            continue
        if voice_id in excluded:
            continue
        label = entry.get("label")
        display_label = label if isinstance(label, str) and label else voice_id
        voices.append((voice_id, display_label))
    return voices


async def fetch_voxcpm_voices(
    http: SharedAsyncClient,
    base_url: str,
    excluded: frozenset[str],
) -> list[tuple[str, str]]:
    return await fetch_castvoice_voices(
        http,
        f"{base_url.rstrip('/')}/api/v1/tts/voices",
        "voxcpm",
        excluded,
    )


async def fetch_cosyvoice_voices(
    http: SharedAsyncClient,
    base_url: str,
    api_key: str,
    excluded: frozenset[str],
) -> list[tuple[str, str]]:
    """CosyVoice 的 /voices 需要 Bearer token（VoxCPM360 的不用）。"""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    return await fetch_castvoice_voices(
        http,
        f"{base_url.rstrip('/')}/voices",
        COSYVOICE_PROVIDER_NAME,
        excluded,
        headers=headers,
    )


def extract_voice_names(payload: object) -> list[str]:
    if isinstance(payload, dict):
        voices = payload.get("voices")
        candidates = voices if isinstance(voices, list) else payload.keys()
    elif isinstance(payload, list):
        candidates = payload
    else:
        return []

    names: list[str] = []
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            names.append(candidate)
        elif isinstance(candidate, dict):
            name = candidate.get("name")
            if isinstance(name, str) and name:
                names.append(name)
    return names


def prepend_default_voice(voices: list[str], default_voice: str) -> list[str]:
    if not default_voice or default_voice in voices:
        return voices
    return [default_voice, *voices]


async def build_tts_provider_catalog(
    cfg: Any,
    http: SharedAsyncClient,
) -> list[dict]:
    """Every configured provider and its voices, for unrestricted admins."""
    providers: list[dict] = [
        {"id": "auto", "name": "自動", "default_voice": "", "voices": []},
    ]

    if cfg.tts_indextts_url:
        # 探測 IndexTTS 健康狀態：抓不到 voices（容器掛掉/不可達）就不顯示，
        # 避免選單列出一個會 502 的 provider。auto 仍由 backend fallback 處理。
        fetched_voices = await fetch_indextts_voices(
            http,
            cfg.tts_indextts_url,
            cfg.gateway_internal_token,
        )
        if fetched_voices:
            providers.append({
                "id": "indextts",
                "name": "IndexTTS",
                "default_voice": cfg.tts_indextts_default_character,
                "voices": prepend_default_voice(
                    fetched_voices,
                    cfg.tts_indextts_default_character,
                ),
            })

    if cfg.tts_voxcpm_url:
        # 同 IndexTTS：抓不到 voices 就不列，避免選單出現會 502 的 provider。
        voxcpm_voices = [
            voice_id
            for voice_id, _label in await fetch_voxcpm_voices(
                http,
                cfg.tts_voxcpm_url,
                excluded_voices(cfg, "tts_voxcpm_excluded_voices"),
            )
        ]
        if voxcpm_voices:
            default_voice = cfg.tts_voxcpm_default_voice or VOXCPM_DEFAULT_VOICE
            providers.append({
                "id": VOXCPM_PROVIDER_NAME,
                "name": "VoxCPM",
                "default_voice": default_voice,
                "voices": prepend_default_voice(voxcpm_voices, default_voice),
            })

    if cfg.tts_cosyvoice_url:
        # 同 IndexTTS：抓不到 voices 就不列，避免選單出現會 502 的 provider。
        cosyvoice_voices = [
            voice_id
            for voice_id, _label in await fetch_cosyvoice_voices(
                http,
                cfg.tts_cosyvoice_url,
                cfg.tts_cosyvoice_api_key,
                excluded_voices(cfg, "tts_cosyvoice_excluded_voices"),
            )
        ]
        if cosyvoice_voices:
            default_voice = (
                cfg.tts_cosyvoice_default_voice or COSYVOICE_DEFAULT_VOICE
            )
            providers.append({
                "id": COSYVOICE_PROVIDER_NAME,
                "name": "CosyVoice",
                "default_voice": default_voice,
                "voices": prepend_default_voice(cosyvoice_voices, default_voice),
            })

    if cfg.tts_gcp_enabled:
        providers.append({
            "id": "gcp",
            "name": "GCP TTS",
            "default_voice": cfg.tts_gcp_voice_name,
            "voices": [cfg.tts_gcp_voice_name],
        })

    if cfg.tts_aws_enabled:
        providers.append({
            "id": "aws",
            "name": "AWS Polly",
            "default_voice": cfg.tts_aws_polly_voice_id,
            "voices": [cfg.tts_aws_polly_voice_id],
        })

    if cfg.tts_gemini_url:
        fetched_voices = await fetch_gemini_voices(http, cfg.tts_gemini_url)
        if fetched_voices:
            providers.append({
                "id": GEMINI_PROVIDER_NAME,
                "name": "Gemini TTS",
                "default_voice": GEMINI_DEFAULT_VOICE,
                "voices": prepend_default_voice(
                    fetched_voices,
                    GEMINI_DEFAULT_VOICE,
                ),
            })

    if cfg.edge_tts_enabled:
        voices = list(EDGE_TTS_VOICES)
        if cfg.edge_tts_voice not in voices:
            voices.insert(0, cfg.edge_tts_voice)
        providers.append({
            "id": "edge-tts",
            "name": "Edge TTS",
            "default_voice": cfg.edge_tts_voice,
            "voices": voices,
        })

    return providers

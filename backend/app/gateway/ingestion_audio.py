"""Audio ingestion — SenseVoice, Breeze-ASR, or the OpenAI Whisper API."""

from __future__ import annotations

import logging
from pathlib import Path

from openai import AsyncOpenAI

from app.config import get_tts_config
from app.gateway.ingestion import IngestionResult
from app.http_client import SharedAsyncClient

logger = logging.getLogger("gateway.ingestion_audio")

# 分開設 connect 與 read：轉寫是 GPU 推論，排隊時久一點正常（實測 5 秒音檔
# 0.8–1.5 秒），但機器整台不通時不該也等兩分鐘——那會把一台死掉的 ASR 變成
# 卡住整個 gateway 的請求槽，連回「音訊轉錄失敗」都得等到逾時才輪得到。
_http = SharedAsyncClient(connect=5, read=120, write=30, pool=5)


async def _transcribe_openai(file_path: str, trace_id: str) -> str:
    """Transcribe audio using OpenAI Whisper API."""
    cfg = get_tts_config()
    client_kwargs: dict = {"api_key": cfg.whisper_api_key}
    if cfg.vision_llm_base_url:
        client_kwargs["base_url"] = cfg.vision_llm_base_url

    client = AsyncOpenAI(**client_kwargs)
    with open(file_path, "rb") as audio_file:
        response = await client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="zh",
        )
    return response.text


async def _transcribe_sensevoice(file_path: str, trace_id: str) -> str:
    """Transcribe via SenseVoice-Small (POST /api/v1/asr).

    送 multipart ``files`` + ``keys``，回 ``{"result": [{"key", "text",
    "raw_text", "clean_text"}]}``。取 ``clean_text``：``text`` 尾端會附情緒
    emoji，``raw_text`` 還帶著 ``<|zh|><|HAPPY|>`` 這類控制標記，兩者都不該
    進到 prompt 裡。臺語語音會保留臺語用字。
    """
    cfg = get_tts_config()
    url = cfg.asr_sensevoice_url.rstrip("/")
    if not url:
        raise RuntimeError("ASR_SENSEVOICE_URL is not configured")

    name = Path(file_path).name
    response = await _http.get().post(
        f"{url}/api/v1/asr",
        files={"files": (name, Path(file_path).read_bytes())},
        data={"keys": name, "lang": "auto"},
    )
    response.raise_for_status()
    results = response.json().get("result") or []
    if not results:
        raise RuntimeError("SenseVoice returned no result")
    first = results[0]
    return str(first.get("clean_text") or first.get("text") or "").strip()


async def _transcribe_breeze(file_path: str, trace_id: str) -> str:
    """Transcribe via Breeze-ASR-360 (POST /transcribe, multipart ``file``).

    整個音檔一次送出——這個服務沒有串流端點，所以使用者講完才開始算延遲。
    臺語語音會轉寫成華語文字：語意保留、用字不保留。
    """
    cfg = get_tts_config()
    url = cfg.asr_breeze_url.rstrip("/")
    if not url:
        raise RuntimeError("ASR_BREEZE_URL is not configured")

    name = Path(file_path).name
    response = await _http.get().post(
        f"{url}/transcribe",
        files={"file": (name, Path(file_path).read_bytes())},
    )
    response.raise_for_status()
    return str(response.json().get("text", "")).strip()



# provider 名稱 → 轉寫函式。
_TRANSCRIBERS: dict[str, object] = {
    "sensevoice": _transcribe_sensevoice,
    "breeze": _transcribe_breeze,
    "openai": _transcribe_openai,
}


def _active_provider(cfg) -> str:
    """The operator's stored choice, or the environment default.

    設定表只存「被人改過」的項目：沒有紀錄就用 .env，所以新部署不必先寫一
    輪設定才能啟動。讀失敗（資料庫還沒 migrate、或整個 auth runtime 沒起來）
    也回退到 .env——語音辨識不該因為一張設定表而停擺。
    """
    try:
        from app.auth.runtime import get_auth_runtime
        from app.auth.settings_repository import ASR_PROVIDER_KEY

        stored = get_auth_runtime().settings.get(ASR_PROVIDER_KEY)
    except Exception as exc:
        logger.debug("asr_provider_setting_unavailable err=%s", exc)
        return cfg.whisper_provider
    return stored or cfg.whisper_provider


def _resolve_chain(cfg) -> list[str]:
    """Ordered ASR providers to try: the configured one, then the rest.

    一台 GPU 節點重啟就讓每一輪語音變成「音訊轉錄失敗」送進 prompt，模型會
    把那六個字當成使用者說的話——那不是降級，是講錯話。TTS 早就有 bounded
    fallback chain，ASR 沒理由只有單點。只排入設定齊全的 provider：沒填
    URL 的排進來只會白等一次連線逾時。
    """
    configured = [
        name for name in (_active_provider(cfg), *_TRANSCRIBERS)
        if name in _TRANSCRIBERS
    ]
    ordered: list[str] = []
    for name in configured:
        if name in ordered or not _provider_ready(cfg, name):
            continue
        ordered.append(name)
    return ordered


def _provider_ready(cfg, name: str) -> bool:
    if name == "sensevoice":
        return bool(cfg.asr_sensevoice_url)
    if name == "breeze":
        return bool(cfg.asr_breeze_url)
    return bool(cfg.whisper_api_key)


async def transcribe(file_path: str, trace_id: str) -> IngestionResult:
    """Transcribe audio, falling back through the other configured providers.

    Returns IngestionResult with content_type="audio_transcription".
    """
    cfg = get_tts_config()
    chain = _resolve_chain(cfg)
    logger.info(
        "transcribe trace_id=%s provider=%s chain=%s",
        trace_id, _active_provider(cfg), ",".join(chain),
    )

    for name in chain:
        transcriber = _TRANSCRIBERS[name]
        try:
            content = await transcriber(file_path, trace_id)
        except Exception as exc:
            logger.warning(
                "transcription_attempt_failed trace_id=%s provider=%s err=%s",
                trace_id, name, exc,
            )
            continue

        logger.info(
            "transcription_ok trace_id=%s provider=%s chars=%d",
            trace_id, name, len(content),
        )
        return IngestionResult(content_type="audio_transcription", content=content)

    logger.error("transcription_failed trace_id=%s tried=%s", trace_id, ",".join(chain))
    return IngestionResult(
        content_type="audio_transcription",
        content="（音訊轉錄失敗）",
    )

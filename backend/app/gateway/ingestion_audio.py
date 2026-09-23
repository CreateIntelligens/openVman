"""Audio ingestion — Breeze-ASR, Xiaomi, SenseVoice, or the OpenAI Whisper API."""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from openai import AsyncOpenAI

from app.config import get_tts_config
from app.gateway.ingestion import IngestionResult
from app.http_client import SharedAsyncClient
from app.utils.chinese import convert_to_traditional

logger = logging.getLogger("gateway.ingestion_audio")

# 分開設 connect 與 read：轉寫是 GPU 推論，排隊時久一點正常（實測 5 秒音檔
# 0.8–1.5 秒），但機器整台不通時不該也等兩分鐘——那會把一台死掉的 ASR 變成
# 卡住整個 gateway 的請求槽，連回「音訊轉錄失敗」都得等到逾時才輪得到。
_http = SharedAsyncClient(connect=5, read=120, write=30, pool=5)


async def _transcribe_openai(file_path: str, trace_id: str) -> str:
    """Transcribe audio with OpenAI, letting the model detect the language.

    不帶 language：寫死 zh 會讓英文、西語被硬轉成中文（鶴記要中英西三語）。
    """
    cfg = get_tts_config()
    client_kwargs: dict = {"api_key": cfg.whisper_api_key}
    if cfg.asr_openai_base_url:
        client_kwargs["base_url"] = cfg.asr_openai_base_url

    client = AsyncOpenAI(**client_kwargs)
    with open(file_path, "rb") as audio_file:
        response = await client.audio.transcriptions.create(
            model=cfg.asr_openai_model,
            file=audio_file,
        )
    return response.text


# 引擎能直接吃的容器格式。瀏覽器 MediaRecorder 錄出來的是 webm/opus，
# SenseVoice 對它回 500（Breeze 可以，但不能只讓一家能用）。
_NATIVE_SUFFIXES = frozenset({".wav", ".mp3", ".flac", ".m4a", ".ogg"})


def _as_wav(file_path: str) -> tuple[str, str | None]:
    """Return a path the engines accept, plus a temp file to clean up.

    已是原生格式就原樣回傳，不白跑一次 ffmpeg。轉檔輸出 16 kHz 單聲道：
    兩家引擎內部都會降到這個取樣率，先降可以少傳幾倍的資料。
    """
    if Path(file_path).suffix.lower() in _NATIVE_SUFFIXES:
        return file_path, None

    handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    handle.close()
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", file_path,
            "-ac", "1", "-ar", "16000",
            handle.name,
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        Path(handle.name).unlink(missing_ok=True)
        raise RuntimeError(f"audio conversion failed: {result.stderr[:200]}")
    return handle.name, handle.name


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

    source, scratch = _as_wav(file_path)
    try:
        name = Path(source).name
        response = await _http.get().post(
            f"{url}/api/v1/asr",
            files={"files": (name, Path(source).read_bytes())},
            data={"keys": name, "lang": "auto"},
        )
    finally:
        if scratch:
            Path(scratch).unlink(missing_ok=True)
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

    source, scratch = _as_wav(file_path)
    try:
        response = await _http.get().post(
            f"{url}/transcribe",
            files={"file": (Path(source).name, Path(source).read_bytes())},
        )
    finally:
        if scratch:
            Path(scratch).unlink(missing_ok=True)
    response.raise_for_status()
    return str(response.json().get("text", "")).strip()


async def _transcribe_xiaomi(file_path: str, trace_id: str) -> str:
    """Transcribe via Xiaomi-CocktailASR-1 (POST /transcribe, target + ref).

    這是目標語者模型：要一段參考聲紋 ``ref``，只轉錄 ``ref`` 那個人的聲音，
    對不上就回空字串（``rejected``）。我們沒有聲紋註冊流程，所以把同一個音檔
    同時當 target 與 ref 送出——自己跟自己 100% 吻合，語者閘門必然放行，效果
    等同一般 ASR。實測 ref 換成別人的聲音仍會 rejected，閘門沒有被繞過。

    輸出是簡體，轉成繁體才能跟其他 provider 一致。
    """
    cfg = get_tts_config()
    url = cfg.asr_xiaomi_url.rstrip("/")
    if not url:
        raise RuntimeError("ASR_XIAOMI_URL is not configured")

    source, scratch = _as_wav(file_path)
    try:
        payload = Path(source).read_bytes()
        name = Path(source).name
        response = await _http.get().post(
            f"{url}/transcribe",
            files={
                "target": (name, payload),
                "ref": (name, payload),
            },
        )
    finally:
        if scratch:
            Path(scratch).unlink(missing_ok=True)
    response.raise_for_status()
    body = response.json()
    # rejected 代表語者閘門擋下來。self-reference 下不該發生，真的發生就是
    # 音檔有問題，回空字串會讓 chain 誤以為成功，所以往上拋讓它 fallback。
    if body.get("rejected"):
        raise RuntimeError("Xiaomi ASR rejected the clip (speaker gate)")
    return convert_to_traditional(str(body.get("text", "")).strip())


# provider 名稱 → 轉寫函式。
# 順序就是 fallback 順序（設定選的那個會被提到最前面）。預設把輸出華語的
# 排在前面：使用者要的是華語逐字稿，臺語漢字只在全都掛掉時才聊勝於無。
_TRANSCRIBERS: dict[str, object] = {
    "breeze": _transcribe_breeze,
    "xiaomi": _transcribe_xiaomi,
    "sensevoice": _transcribe_sensevoice,
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
        return cfg.asr_provider
    return stored or cfg.asr_provider


def _resolve_chain(cfg, preferred: str | None = None) -> list[str]:
    """Ordered ASR providers to try: the preferred one, then the rest.

    一台 GPU 節點重啟就讓每一輪語音變成「音訊轉錄失敗」送進 prompt，模型會
    把那六個字當成使用者說的話——那不是降級，是講錯話。TTS 早就有 bounded
    fallback chain，ASR 沒理由只有單點。只排入設定齊全的 provider：沒填
    URL 的排進來只會白等一次連線逾時。

    preferred 是這個使用者自己選的引擎，排在最前面；其餘順序不變，所以他選
    的那家掛掉時仍有備援。不認得的名字（例如瀏覽器端的 browser）直接忽略：
    它根本不會走到這裡，音檔不會送上來。
    """
    configured = [
        name for name in (preferred, _active_provider(cfg), *_TRANSCRIBERS)
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
    if name == "xiaomi":
        return bool(cfg.asr_xiaomi_url)
    return bool(cfg.whisper_api_key)


async def transcribe(
    file_path: str, trace_id: str, preferred: str | None = None,
) -> IngestionResult:
    """Transcribe audio, falling back through the other configured providers.

    Returns IngestionResult with content_type="audio_transcription".
    """
    cfg = get_tts_config()
    chain = _resolve_chain(cfg, preferred)
    logger.info(
        "transcribe trace_id=%s provider=%s preferred=%s chain=%s",
        trace_id, _active_provider(cfg), preferred or "-", ",".join(chain),
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

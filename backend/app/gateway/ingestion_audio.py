"""Audio ingestion — Breeze-ASR, Confucius4-R2T2, Xiaomi, SenseVoice, or the OpenAI Whisper API."""

from __future__ import annotations

import logging
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
import openai
from openai import AsyncOpenAI

from app import language_routes as language_routes_mod
from app.config import get_tts_config
from app.gateway.ingestion import IngestionResult
from app.http_client import SharedAsyncClient
from app.utils.chinese import convert_to_traditional

logger = logging.getLogger("gateway.ingestion_audio")

# 分開設 connect 與 read：轉寫是 GPU 推論，排隊時久一點正常（實測 5 秒音檔
# 0.8–1.5 秒），但機器整台不通時不該也等兩分鐘——那會把一台死掉的 ASR 變成
# 卡住整個 gateway 的請求槽，連回「音訊轉錄失敗」都得等到逾時才輪得到。
_http = SharedAsyncClient(connect=5, read=120, write=30, pool=5)


async def _transcribe_openai(file_path: str, trace_id: str, prompt: str = "") -> str:
    """Transcribe audio with OpenAI, letting the model detect the language.

    不帶 language：寫死 zh 會讓英文、西語被硬轉成中文（鶴記要中英西三語）。
    """
    cfg = get_tts_config()
    client_kwargs: dict = {"api_key": cfg.whisper_api_key}
    if cfg.asr_openai_base_url:
        client_kwargs["base_url"] = cfg.asr_openai_base_url

    client = AsyncOpenAI(**client_kwargs)
    extra = {"prompt": prompt} if prompt else {}
    with open(file_path, "rb") as audio_file:
        response = await client.audio.transcriptions.create(
            model=cfg.asr_openai_model,
            file=audio_file,
            **extra,
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


async def _transcribe_sensevoice(file_path: str, trace_id: str, prompt: str = "") -> str:
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


async def _transcribe_breeze(file_path: str, trace_id: str, prompt: str = "") -> str:
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
            # 專案詞表當 Whisper 前文（Breeze 1.4 起）：「污泥泵」不再聽成「烏尼本」。
            data={"prompt": prompt} if prompt else None,
        )
    finally:
        if scratch:
            Path(scratch).unlink(missing_ok=True)
    response.raise_for_status()
    return collapse_repeated_transcript(str(response.json().get("text", "")).strip())


# 太短的片段（「好 好」「對對」）可能真的是這樣講，不收。
_MIN_REPEATED_UNIT_CHARS = 4


def collapse_repeated_transcript(text: str) -> str:
    """Return one copy when the whole transcript is the same sentence repeated.

    Breeze 偶爾把整句吐兩三次（真人台語朗讀 20 句有 3 句），原樣送進 Brain
    等於使用者講了三遍。只處理「整段剛好是同一句重複」，不動部分重複。
    """
    tokens = text.split()
    for size in range(1, len(tokens) // 2 + 1):
        unit = tokens[:size]
        if (
            len(tokens) % size == 0
            and tokens == unit * (len(tokens) // size)
            and len("".join(unit)) >= _MIN_REPEATED_UNIT_CHARS
        ):
            return " ".join(unit)
    if len(tokens) == 1:
        # 沒有空白分隔時看整串是不是同一段字重複。
        for size in range(_MIN_REPEATED_UNIT_CHARS, len(text) // 2 + 1):
            if len(text) % size == 0 and text == text[:size] * (len(text) // size):
                return text[:size]
    return text


async def _transcribe_xiaomi(file_path: str, trace_id: str, prompt: str = "") -> str:
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


async def _transcribe_r2t2(
    file_path: str, trace_id: str, prompt: str = "",
    language: str = language_routes_mod.R2T2_CHINESE,
) -> str:
    """Transcribe via Confucius4-R2T2 (POST /transcribe, multipart ``file``).

    ``language`` 照專案語言分流（language_routes.r2t2_language），跟串流同一套：R2T2 不會
    自己判斷，西日韓當中文解碼會整句壞掉；不帶 language 則會把帶口音的華語跑成葡萄牙文。
    專案詞表放 ``context``（Qwen3-ASR 的熱詞提示）。中文輸出簡體，轉繁才跟其他家一致。
    """
    cfg = get_tts_config()
    if not cfg.asr_r2t2_url:
        raise RuntimeError("ASR_R2T2_URL is not configured")
    return await _r2t2_file(cfg.asr_r2t2_url, file_path, prompt, language, None)


async def _transcribe_r2t2_dev(
    file_path: str, trace_id: str, prompt: str = "",
    language: str = language_routes_mod.R2T2_CHINESE,
) -> str:
    """Same request against the R2T2 dev host (deployed on .37), with a bounded wait."""
    cfg = get_tts_config()
    if not cfg.asr_r2t2_dev_url:
        raise RuntimeError("ASR_R2T2_DEV_URL is not configured")
    return await _r2t2_file(
        cfg.asr_r2t2_dev_url, file_path, prompt, language,
        cfg.asr_r2t2_dev_timeout_seconds,
    )


async def _r2t2_file(
    url: str, file_path: str, prompt: str, language: str, timeout: float | None,
) -> str:
    source, scratch = _as_wav(file_path)
    try:
        return await _r2t2_request(
            url.rstrip("/"), Path(source).read_bytes(), Path(source).name,
            prompt, language, timeout,
        )
    finally:
        if scratch:
            Path(scratch).unlink(missing_ok=True)


async def _r2t2_request(
    url: str, audio: bytes, filename: str, prompt: str, language: str,
    timeout: float | None,
) -> str:
    response = await _http.get().post(
        f"{url}/transcribe",
        files={"file": (filename, audio)},
        data={"language": language, "context": prompt},
        **({"timeout": timeout} if timeout else {}),
    )
    response.raise_for_status()
    body = response.json()
    if body.get("status") == "error":
        raise RuntimeError(f"R2T2 ASR error: {body.get('message', '')}")
    text = str(body.get("text", "")).strip()
    if language_routes_mod.r2t2_outputs_chinese(language):
        return convert_to_traditional(text)
    return text


# provider 名稱 → 轉寫函式。
# 順序就是 fallback 順序（使用者選的、部署預設 ASR_PROVIDER 會被提到最前面）。預設把輸出華語的
# 排在前面：使用者要的是華語逐字稿，臺語漢字只在全都掛掉時才聊勝於無。
_TRANSCRIBERS: dict[str, object] = {
    "breeze": _transcribe_breeze,
    "r2t2": _transcribe_r2t2,
    "r2t2-dev": _transcribe_r2t2_dev,
    "xiaomi": _transcribe_xiaomi,
    "sensevoice": _transcribe_sensevoice,
    "openai": _transcribe_openai,
}


_OPT_IN_TRANSCRIBERS = frozenset({"r2t2-dev"})
# 要照語言分流指定解碼語言的引擎；其他家自己判斷語言或只聽華語。
_LANGUAGE_AWARE_TRANSCRIBERS = frozenset({"r2t2", "r2t2-dev"})


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
        name for name in (preferred, cfg.asr_provider, *_TRANSCRIBERS)
        if name in _TRANSCRIBERS
        # dev 機只在自己被選時用，不當別人的備援：它慢就讓這一句多等，不該拖累其他人。
        and (name not in _OPT_IN_TRANSCRIBERS or name in (preferred, cfg.asr_provider))
    ]
    ordered: list[str] = []
    for name in configured:
        if name in ordered or not _provider_ready(cfg, name):
            continue
        ordered.append(name)
    return ordered


# 連不上的引擎暫停這麼久，期間直接跳過：小米那台（.19）停機後，Breeze 一掛每句話
# 都要先白等 3.3 秒連線失敗才換 SenseVoice。時間到讓下一個請求去試，通了就恢復原順序。
# 每個 worker 各記各的，重啟就清空，最多多試一次。
_UNREACHABLE_COOLDOWN_SECONDS = 60.0
_unreachable_until: dict[str, float] = {}


def _is_unreachable(exc: Exception) -> bool:
    """Connection-level failures only: an HTTP error means the node is up and answering."""
    return isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, openai.APIConnectionError))


def _cooling_down(name: str) -> bool:
    until = _unreachable_until.get(name)
    if until is None:
        return False
    if time.monotonic() >= until:
        _unreachable_until.pop(name, None)
        return False
    return True


def _skip_unreachable(chain: list[str]) -> list[str]:
    """Drop providers that just failed to connect; all of them down means try them anyway."""
    available = [name for name in chain if not _cooling_down(name)]
    return available or chain


def _provider_ready(cfg, name: str) -> bool:
    if name == "sensevoice":
        return bool(cfg.asr_sensevoice_url)
    if name == "breeze":
        return bool(cfg.asr_breeze_url)
    if name == "xiaomi":
        return bool(cfg.asr_xiaomi_url)
    if name == "r2t2":
        return bool(cfg.asr_r2t2_url)
    if name == "r2t2-dev":
        return bool(cfg.asr_r2t2_dev_url)
    return bool(cfg.whisper_api_key)


async def transcribe(
    file_path: str, trace_id: str, preferred: str | None = None, prompt: str = "",
    routes: list[str] | None = None,
) -> IngestionResult:
    """Transcribe audio, falling back through the other configured providers.

    ``prompt`` 是專案的專有名詞詞表；Breeze、OpenAI（prompt）與 R2T2（context）會用，
    SenseVoice、小米忽略。``routes`` 是專案生效的語言分流，R2T2 照它決定解碼語言；
    沒給（例如聊天附件）就當華語。

    Returns IngestionResult with content_type="audio_transcription".
    """
    cfg = get_tts_config()
    configured = _resolve_chain(cfg, preferred)
    chain = _skip_unreachable(configured)
    logger.info(
        "transcribe trace_id=%s provider=%s preferred=%s chain=%s skipped=%s",
        trace_id, cfg.asr_provider, preferred or "-", ",".join(chain),
        ",".join(name for name in configured if name not in chain) or "-",
    )

    language = {"language": language_routes_mod.r2t2_language(routes or [])}
    for name in chain:
        transcriber = _TRANSCRIBERS[name]
        extra = language if name in _LANGUAGE_AWARE_TRANSCRIBERS else {}
        try:
            content = await transcriber(file_path, trace_id, prompt=prompt, **extra)
        except Exception as exc:
            logger.warning(
                "transcription_attempt_failed trace_id=%s provider=%s err=%s",
                trace_id, name, exc,
            )
            if _is_unreachable(exc):
                _unreachable_until[name] = time.monotonic() + _UNREACHABLE_COOLDOWN_SECONDS
                logger.warning(
                    "asr_provider_unreachable provider=%s skip_for=%.0fs",
                    name, _UNREACHABLE_COOLDOWN_SECONDS,
                )
            continue
        _unreachable_until.pop(name, None)

        logger.info(
            "transcription_ok trace_id=%s provider=%s chars=%d",
            trace_id, name, len(content),
        )
        return IngestionResult(
            content_type="audio_transcription", content=content, provider=name,
        )

    logger.error("transcription_failed trace_id=%s tried=%s", trace_id, ",".join(chain))
    return IngestionResult(
        content_type="audio_transcription",
        content="（音訊轉錄失敗）",
    )

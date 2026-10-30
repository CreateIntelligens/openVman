"""Audio ingestion — Breeze-ASR, Confucius4-R2T2, SenseVoice, or the OpenAI Whisper API."""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import httpx
from openai import AsyncOpenAI

from app import language_routes as language_routes_mod
from app.config import get_tts_config
from app.gateway.ingestion import IngestionResult
from app.http_client import SharedAsyncClient
from app.upstream_guard import (
    ASR_BREAKER,
    OK,
    SKIPPED_BREAKER,
    SKIPPED_DEADLINE,
    Deadline,
    HopTimeout,
    asr_chain_seconds,
    asr_node_seconds,
    classify_outcome,
    clip_seconds,
    describe_error,
    emit_attempt,
    ffmpeg_seconds,
    host_of,
    knob,
    set_clip_seconds,
    worth_trying,
)
from app.utils.chinese import convert_to_traditional

logger = logging.getLogger("gateway.ingestion_audio")

# 分開設 connect 與 read：轉寫是 GPU 推論，排隊時久一點正常（實測 5 秒音檔
# 0.8–1.5 秒），但機器整台不通時不該也等兩分鐘——那會把一台死掉的 ASR 變成
# 卡住整個 gateway 的請求槽，連回「音訊轉錄失敗」都得等到逾時才輪得到。
# read 只是單次讀取的上限；每一站真正的牆鐘由 transcribe() 依音訊長度另外管。
def _asr_http_timeout() -> httpx.Timeout:
    cfg = get_tts_config()
    connect = knob(cfg, "asr_connect_timeout_seconds")
    longest = knob(cfg, "asr_node_max_seconds")
    return httpx.Timeout(connect=connect, read=longest, write=longest, pool=connect)


_http = SharedAsyncClient(timeout_factory=_asr_http_timeout)


def _bounded_timeout(seconds: float) -> httpx.Timeout:
    """R2T2 dev's own short wait, with the shared short connect."""
    connect = min(seconds, knob(get_tts_config(), "asr_connect_timeout_seconds"))
    return httpx.Timeout(connect=connect, read=seconds, write=seconds, pool=connect)


async def _transcribe_openai(file_path: str, trace_id: str, prompt: str = "") -> str:
    """Transcribe audio with OpenAI, letting the model detect the language.

    不帶 language：寫死 zh 會讓英文、西語被硬轉成中文（鶴記要中英西三語）。
    """
    cfg = get_tts_config()
    client_kwargs: dict = {"api_key": cfg.whisper_api_key}
    if cfg.asr_openai_base_url:
        client_kwargs["base_url"] = cfg.asr_openai_base_url

    # SDK 預設等 600 秒、失敗再重試兩次；這裡只等這一站的預算、不重試，換下一家。
    client = AsyncOpenAI(
        **client_kwargs,
        timeout=httpx.Timeout(
            asr_node_seconds(cfg, clip_seconds()),
            connect=knob(cfg, "asr_connect_timeout_seconds"),
        ),
        max_retries=0,
    )
    extra = {"prompt": prompt} if prompt else {}
    with open(file_path, "rb") as audio_file:
        response = await client.audio.transcriptions.create(
            model=cfg.asr_openai_model,
            file=audio_file,
            **extra,
        )
    text = response.text.strip()
    # 中文會回簡體，要跟其他家一樣轉繁；有假名就是日文，轉了會把「学校」改成「學校」。
    if _KANA.search(text):
        return text
    return convert_to_traditional(text)


_KANA = re.compile(r"[\u3040-\u30ff]")


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
        timeout=ffmpeg_seconds(get_tts_config(), clip_seconds()),
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

    source, scratch = await asyncio.to_thread(_as_wav, file_path)
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

    source, scratch = await asyncio.to_thread(_as_wav, file_path)
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
    source, scratch = await asyncio.to_thread(_as_wav, file_path)
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
        **({"timeout": _bounded_timeout(timeout)} if timeout else {}),
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
    "sensevoice": _transcribe_sensevoice,
    "openai": _transcribe_openai,
}


_OPT_IN_TRANSCRIBERS = frozenset({"r2t2-dev"})
# 要照語言分流指定解碼語言的引擎；其他家自己判斷語言或只聽華語。
_LANGUAGE_AWARE_TRANSCRIBERS = frozenset({"r2t2", "r2t2-dev"})


def _resolve_chain(
    cfg, preferred: str | None = None, order: tuple[str, ...] | list[str] = (),
) -> list[str]:
    """Ordered ASR providers to try: the preferred one, then the rest.

    一台 GPU 節點重啟就讓每一輪語音變成「音訊轉錄失敗」送進 prompt，模型會
    把那六個字當成使用者說的話——那不是降級，是講錯話。TTS 早就有 bounded
    fallback chain，ASR 沒理由只有單點。只排入設定齊全的 provider：沒填
    URL 的排進來只會白等一次連線逾時。

    preferred 是這個使用者自己選的引擎，排在最前面；其餘順序不變，所以他選
    的那家掛掉時仍有備援。不認得的名字（例如瀏覽器端的 browser）直接忽略：
    它根本不會走到這裡，音檔不會送上來。
    """
    # 專案設了順位：指定的引擎之後只照順位試，不再接部署的鏈。
    rest = (*order,) if order else (cfg.asr_provider, *_TRANSCRIBERS)
    configured = [
        name for name in (preferred, *rest)
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


# 暫停中的引擎直接跳過：備援裡有一台停機時，主引擎一掛每句話都要先白等連線失敗
# 才換下一家。連不上立刻暫停；逾時與 5xx 連續兩次才暫停（upstream_guard.Breaker）。
# 時間到讓下一個請求去試，通了就恢復原順序。每個 worker 各記各的，重啟就清空。
# 暫停長度是 UPSTREAM_BREAKER_COOLDOWN_SECONDS，這裡是它的預設值。
_UNREACHABLE_COOLDOWN_SECONDS = 60.0
_unreachable_until: dict[str, float] = {}


def _provider_host(cfg, name: str) -> str:
    if name == "openai":
        return host_of(getattr(cfg, "asr_openai_base_url", "") or "https://api.openai.com")
    url = getattr(cfg, f"asr_{name.replace('-', '_')}_url", "")
    return host_of(url) if isinstance(url, str) else ""


def _clip_seconds(file_path: str) -> float | None:
    """Clip length for the timeout formula; ``None`` (= assume the longest) when unknown."""
    try:
        with wave.open(file_path, "rb") as audio:
            return audio.getnframes() / audio.getframerate()
    except (wave.Error, EOFError, OSError, ZeroDivisionError):
        pass
    try:
        from app.utils.media import probe_media

        return probe_media(file_path).duration_seconds
    except Exception:  # noqa: BLE001 - 量不到就用上限，不擋辨識
        return None


def _cooling_down(name: str) -> bool:
    # 背景健康探測判定掛掉的也算（upstream_probe）。
    if ASR_BREAKER.probe_down(name):
        return True
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


def configured_providers() -> list[str]:
    """Server-side engines whose URL or key is set, in fallback order.

    後台試辨識只列這些：沒設定的引擎選了也只會被備援接走，看起來像它辨識的。
    """
    cfg = get_tts_config()
    return [name for name in _TRANSCRIBERS if _provider_ready(cfg, name)]


def _provider_ready(cfg, name: str) -> bool:
    if name == "sensevoice":
        return bool(cfg.asr_sensevoice_url)
    if name == "breeze":
        return bool(cfg.asr_breeze_url)
    if name == "r2t2":
        return bool(cfg.asr_r2t2_url)
    if name == "r2t2-dev":
        return bool(cfg.asr_r2t2_dev_url)
    return bool(cfg.whisper_api_key)


async def transcribe(
    file_path: str, trace_id: str, preferred: str | None = None, prompt: str = "",
    routes: list[str] | None = None,
    *,
    allowed_providers: set[str] | None = None,
    order: tuple[str, ...] | list[str] = (),
    audio_seconds: float | None = None,
) -> IngestionResult:
    """Transcribe audio, falling back through the other configured providers.

    ``prompt`` 是專案的專有名詞詞表；Breeze、OpenAI（prompt）與 R2T2（context）會用，
    SenseVoice 忽略。``routes`` 是專案生效的語言分流，R2T2 照它決定解碼語言；
    沒給（例如聊天附件）就當華語。

    ``allowed_providers`` constrains every attempt, including fallback. Internal
    ingestion callers may omit it; account-facing routes supply their scope.

    Returns IngestionResult with content_type="audio_transcription".
    """
    cfg = get_tts_config()
    configured = _resolve_chain(cfg, preferred, order)
    if allowed_providers is not None:
        configured = [name for name in configured if name in allowed_providers]
    chain = _skip_unreachable(configured)
    logger.info(
        "transcribe trace_id=%s provider=%s preferred=%s chain=%s skipped=%s",
        trace_id, cfg.asr_provider, preferred or "-", ",".join(chain),
        ",".join(name for name in configured if name not in chain) or "-",
    )

    for name in configured:
        if name not in chain:
            emit_attempt(
                "asr", name, SKIPPED_BREAKER, 0.0, host=_provider_host(cfg, name),
                error="cooling down", trace_id=trace_id,
            )

    if audio_seconds is None:
        # 上傳路由量過長度就放在 context 裡；其他呼叫端（聊天附件）才自己量。
        audio_seconds = clip_seconds()
    if audio_seconds is None:
        audio_seconds = await asyncio.to_thread(_clip_seconds, file_path)
    # ffmpeg 轉檔在 worker thread 裡讀這個值決定逾時。
    set_clip_seconds(audio_seconds)
    node_seconds = asr_node_seconds(cfg, audio_seconds)
    deadline = Deadline(asr_chain_seconds(cfg, audio_seconds))
    language = {"language": language_routes_mod.r2t2_language(routes or [])}
    for name in chain:
        transcriber = _TRANSCRIBERS[name]
        extra = language if name in _LANGUAGE_AWARE_TRANSCRIBERS else {}
        host = _provider_host(cfg, name)
        seconds = deadline.hop_seconds(node_seconds)
        if name == "r2t2-dev":
            seconds = min(seconds, float(getattr(cfg, "asr_r2t2_dev_timeout_seconds", seconds) or seconds))
        if not worth_trying(seconds, node_seconds):
            emit_attempt(
                "asr", name, SKIPPED_DEADLINE, 0.0, host=host,
                error="chain deadline reached", trace_id=trace_id,
            )
            continue
        started = time.monotonic()
        try:
            try:
                content = await asyncio.wait_for(
                    transcriber(file_path, trace_id, prompt=prompt, **extra), seconds,
                )
            except TimeoutError:
                raise HopTimeout("total", seconds, name) from None
        except Exception as exc:
            outcome, error = classify_outcome(exc)
            logger.warning(
                "transcription_attempt_failed trace_id=%s provider=%s err=%s",
                trace_id, name, describe_error(exc),
            )
            opened = ASR_BREAKER.record_failure(name, exc)
            emit_attempt(
                "asr", name, outcome, (time.monotonic() - started) * 1000, host=host,
                error=error, trace_id=trace_id, budget_ms=round(seconds * 1000),
                audio_seconds=audio_seconds, breaker_opened=opened or None,
            )
            if opened:
                cooldown = knob(cfg, "upstream_breaker_cooldown_seconds")
                _unreachable_until[name] = time.monotonic() + cooldown
                logger.warning(
                    "asr_provider_unreachable provider=%s skip_for=%.0fs",
                    name, cooldown,
                )
            continue
        _unreachable_until.pop(name, None)
        ASR_BREAKER.record_success(name)
        emit_attempt(
            "asr", name, OK, (time.monotonic() - started) * 1000, host=host,
            trace_id=trace_id, budget_ms=round(seconds * 1000), audio_seconds=audio_seconds,
        )

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

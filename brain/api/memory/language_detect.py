"""Guess which language a chat message is written in.

對話紀錄依語言篩選與備份（VH-388／389）要用：Live 轉錄只給文字，前台也
不讓使用者先選語言。寫入時先用字元與常用字規則判斷（即時、不外送），再在
背景問 Jev 校正；規則錯在「ok」「buenos dias」這種沒有特徵字的短句。
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

logger = logging.getLogger(__name__)

# 客戶只用中英西；其他語言與判斷不出來的一律算中文（2026-09-23 使用者決定）。
# nan（台語）只能從聲音判斷：轉錄成文字後是中文字，文字規則永遠不會回 nan。
LANGUAGES = ("zh", "en", "es", "nan")
DEFAULT_LANGUAGE = "zh"
TAIWANESE = "nan"

_LATIN_WORD = re.compile(r"[a-záéíóúüñ]+")
_SPANISH_MARKS = re.compile(r"[¿¡ñ]")
_HAN = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")

_EN_WORDS = frozenset(
    "the an is are was were do does did i you he she it we they my your "
    "what which who how why when where can could would should will have has "
    "and or but for with from to of in on this that please thanks thank hi "
    "hello yes not".split()
)
# 兩種語言都會用的字（a、no、me）不列，否則會互相抵銷。
_ES_WORDS = frozenset(
    "el la los las un una es son está están era fue yo tú usted él ella "
    "nosotros ellos mi tu su qué cuál quién cómo por porque cuándo dónde "
    "puede puedo quiero tiene tengo y o pero para con de del en al este esta "
    "eso favor gracias hola sí muy más te se lo le".split()
)


def detect_language(text: str) -> str:
    """Return "en" or "es" when the text is clearly one of them, else "zh"."""
    lowered = (text or "").lower()
    words = _LATIN_WORD.findall(lowered)
    if not words:
        return DEFAULT_LANGUAGE
    # 中文夾英文型號（EUS、HP）或網址很常見，漢字比拉丁字多就是中文；要先於西語符號
    # 檢查，否則長篇中文文件裡某處一個 ñ 就被判成西語（實際發生在旅遊節目腳本）。
    if len(_HAN.findall(text)) > len(words):
        return DEFAULT_LANGUAGE
    if _SPANISH_MARKS.search(lowered):
        return "es"
    en_hits = sum(word in _EN_WORDS for word in words)
    es_hits = sum(word in _ES_WORDS for word in words)
    if en_hits == es_hits:
        return DEFAULT_LANGUAGE
    return "es" if es_hits > en_hits else "en"


# 台羅的聲調符號：揚抑符、長音符與第八聲的 U+030D；西語只有尖音符，不會撞到。
_TAILO_TONE = re.compile(r"[âêîôûāēīōūǹ]|\u030d")
# 台語漢字常用、華語很少單獨出現的字；比例夠高才算，免得「給予」「欲望」誤判。
_TAIWANESE_HAN = set("佇袂毋阮恁欲予矣咧遮遐佗閣攏猶")
_TAIWANESE_WORDS = ("啥物", "按怎", "無法度", "足濟", "抑是", "敢會")
# 這些華語詞含上面的字，先拿掉再數，免得華語衛教文件被當成台語。
_MANDARIN_COMPOUNDS = re.compile(
    "給予|授予|賦予|予以|欲望|欲求|隨心所欲|內閣|樓閣|閣下|攏絡|遮蔽|遮住|遮擋|遮陽|咧嘴|猶豫|猶如|猶太"
)


def detect_document_language(text: str) -> str:
    """Like detect_language, but also recognizes Taiwanese knowledge documents.

    使用者的話轉成文字後，台語也是中文字，所以只有文件判斷會回 nan：台羅拼音，
    或台語特有的漢字用得夠密。判錯可以在後台手動指定。
    """
    words = _LATIN_WORD.findall(text.lower())
    tailo_words = [w for w in re.findall(r"\S+", text) if _TAILO_TONE.search(w)]
    if len(tailo_words) >= 3 and len(tailo_words) >= 0.1 * max(len(words), 1):
        return TAIWANESE
    han = _HAN.findall(text)
    if han:
        stripped = _MANDARIN_COMPOUNDS.sub("", text)
        markers = sum(ch in _TAIWANESE_HAN for ch in stripped) + 2 * sum(
            stripped.count(word) for word in _TAIWANESE_WORDS
        )
        if markers >= 5 and markers >= 0.03 * len(han):
            return TAIWANESE
    return detect_language(text)


def project_has_taiwanese_route(project_id: str) -> bool:
    """Taiwanese is a route only when the admin ticked it in knowledge settings."""
    from knowledge.kb_settings import language_routes

    return TAIWANESE in language_routes(project_id)


def route_language(language: str | None, project_id: str) -> str | None:
    """Map a detected language onto the project's configured routes.

    只有一條分流時回 None（不分流，所有文件都查）；語言不在分流裡就走第一條分流。
    """
    from knowledge.kb_settings import language_routes

    routes = language_routes(project_id)
    if not language or len(routes) <= 1:
        return None
    return language if language in routes else routes[0]


_JEV_QUESTIONS = {
    "en": {
        "instructions": "這句使用者訊息主要是用英文寫的嗎？",
        "criteria": {
            "true": "主要語言是英文",
            "false": "主要語言是中文、西班牙文或其他語言，或只有型號數字",
        },
    },
    "es": {
        "instructions": "這句使用者訊息主要是用西班牙文寫的嗎？",
        "criteria": {
            "true": "主要語言是西班牙文",
            "false": "主要語言是中文、英文或其他語言，或只有型號數字",
        },
    },
}

# Jev 呼叫約 0.5 秒；背景跑，不擋寫入。兩條 worker 足夠應付對話節奏。
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="jev-language")


def detect_language_with_jev(text: str) -> str:
    """Ask Jev whether ``text`` is English or Spanish; anything else is zh."""
    from config import get_settings
    from core.jev_client import jev_nouls

    scores = jev_nouls(
        text, _JEV_QUESTIONS, timeout=get_settings().jev_gate_timeout_seconds,
    )
    best = max(scores, key=scores.__getitem__)
    return best if scores[best] >= 0.5 else DEFAULT_LANGUAGE


def refine_language_in_background(
    text: str, rule_language: str, on_change: Callable[[str], None],
) -> None:
    """Re-check ``text`` with Jev and call ``on_change`` if it disagrees."""
    from config import get_settings
    from core.jev_client import jev_available

    if not text.strip() or not get_settings().jev_language_enabled or not jev_available():
        return

    def _run() -> None:
        try:
            language = detect_language_with_jev(text)
        except Exception as exc:  # noqa: BLE001 - Jev 失敗就留規則的結果
            # 例外訊息可能夾帶回應內容；只記型別。
            logger.warning(json.dumps(
                {"event": "language_jev_failed", "error_type": type(exc).__name__},
            ))
            return
        if language != rule_language:
            on_change(language)

    _executor.submit(_run)


_AUDIO_LANGUAGE_TIMEOUT_MS = 30_000

_AUDIO_LANGUAGE_PROMPT = (
    '這段語音是哪種語言？只能選 zh（華語）、nan（台語）、en、es、other。'
    '只回 JSON：{"language": "..."}'
)


def detect_audio_language(wav_bytes: bytes) -> str:
    """Ask Gemini which language an utterance is in; other is folded into zh.

    合成台語 8 句＋華英西 5 句：3.5-flash-lite 12/13（台語全對）、p50 1.4 秒（scripts/experiments/taigi）。
    """
    from google import genai
    from google.genai import types

    from config import get_settings

    cfg = get_settings()
    # 3.5-flash 實測有一次卡 182 秒；背景工作也要有上限，免得執行緒卡住。
    client = genai.Client(
        api_key=cfg.gemini_api_key,
        http_options=types.HttpOptions(timeout=_AUDIO_LANGUAGE_TIMEOUT_MS),
    )
    response = client.models.generate_content(
        model=cfg.live_audio_language_id_model,
        contents=[
            types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
            _AUDIO_LANGUAGE_PROMPT,
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json", temperature=0,
        ),
    )
    language = str(json.loads(response.text or "{}").get("language", "")).strip()
    return language if language in LANGUAGES else DEFAULT_LANGUAGE

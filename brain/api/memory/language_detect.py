"""Guess which language a chat message is written in.

對話紀錄要能依語言篩選（VH-388），但訊息沒有存語言：Live 轉錄只給文字，
前台也不讓使用者先選語言。這裡用字元與常用字判斷，不呼叫模型，列表每筆
session 都要算一次。只分辨我們真的有客戶用到的語言，其他一律歸「other」。
"""

from __future__ import annotations

import re

LANGUAGES = ("zh", "en", "es", "ja", "ko", "other")

_HANGUL = re.compile(r"[가-힯ᄀ-ᇿ]")
_KANA = re.compile(r"[぀-ヿ]")
_HAN = re.compile(r"[一-鿿㐀-䶿]")
_LATIN_WORD = re.compile(r"[a-záéíóúüñ]+")
_SPANISH_MARKS = re.compile(r"[¿¡ñ]")

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
    """Return one of LANGUAGES, or "" when there is nothing to judge."""
    if not text or not text.strip():
        return ""
    if _HANGUL.search(text):
        return "ko"
    # 日文一定夾假名；只有漢字就當中文。
    if _KANA.search(text):
        return "ja"
    if _HAN.search(text):
        return "zh"

    lowered = text.lower()
    words = _LATIN_WORD.findall(lowered)
    if not words:
        return ""
    if _SPANISH_MARKS.search(lowered):
        return "es"
    en_hits = sum(word in _EN_WORDS for word in words)
    es_hits = sum(word in _ES_WORDS for word in words)
    if es_hits > en_hits:
        return "es"
    if en_hits > es_hits:
        return "en"
    return "other"

"""Pick between a streaming transcript's last interim and its final text.

Gemini 串流辨識講話中給暫定字幕，停頓後整句重判一次當定稿；定稿偶爾反而錯
（「who am i」定稿成「OMI」、定稿成韓文）。不重送音訊，只拿兩段文字問 Jev 哪
個像正確辨識的一句話。分數差不多、Jev 不能用或出錯時一律照定稿送：寧可不修，
也不要把對的定稿換掉。離線驗證見 scripts/experiments/asr-final-judge（20 組 18
組挑對、0 組改錯）。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger("memory.asr_judge")

# 兩個分數差距小於這個就不換：v1 的位置偏誤、v3 的一次翻轉都落在這個範圍內。
DECISION_MARGIN = 0.2

LANGUAGE_NAMES = {
    "zh": "繁體中文",
    "nan": "台語（轉成華語文字）",
    "en": "英文",
    "es": "西班牙文",
    "ja": "日文",
    "ko": "韓文",
}


@dataclass(frozen=True)
class Verdict:
    text: str
    chosen: str  # "interim" | "final"
    scores: dict[str, float] | None = None
    reason: str = ""


def _comparable(text: str) -> str:
    return re.sub(r"[\W_]+", "", text).lower()


_HAN = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_HANGUL = re.compile(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]")
_KANA = re.compile(r"[\u3040-\u30ff]")


def _script_intrusion(interim: str, final: str) -> bool:
    """The final slipped another script into a sentence the interim wrote in one.

    韓文句子夾進漢字（「이 펌프의」定稿成「이 泵의」）、中文句子夾進諺文或假名：
    分流同時有中韓時 Jev 覺得兩句都合理（0.77 對 0.72），挑不出來。日文不算：
    定稿把假名轉成漢字（ほしょう→保証）是正常的。
    """
    if _HANGUL.search(final) and _HANGUL.search(interim):
        return bool(_HAN.search(final)) and not _HAN.search(interim)
    if _HAN.search(final) and _HAN.search(interim) and not _KANA.search(interim):
        return bool(_HANGUL.search(final) or _KANA.search(final)) and not (
            _HANGUL.search(interim) or _KANA.search(interim)
        )
    return False


def _plausible(text: str) -> dict:
    # 各自單獨問，不讓兩個版本互比：互比會偏向排在前面的（v1）。閒聊也要算合理，
    # 否則「who am i」在泵浦諮詢情境下會跟「OMI」一樣低分（v2）。
    return {
        "instructions": f"語音辨識把使用者的話轉成「{text}」，這像是正確辨識出來的一句話嗎？",
        "criteria": {
            "true": "通順、像真人會說的話，是上述語言之一；跟專案無關的閒聊或測試也算。專有名詞（型號、品牌）拼對",
            "false": "有聽錯的同音字（例如把型號聽成別的詞）、無意義的音譯或亂碼、話被截斷，或用了上述以外的語言",
        },
    }


def _project_context(project_id: str, languages: list[str] | None = None) -> str:
    from infra.project_admin import _read_label
    from infra.project_context import resolve_project_context
    from knowledge.kb_settings import language_routes

    try:
        label = _read_label(resolve_project_context(project_id).project_root)
    except Exception:  # noqa: BLE001 - 名稱只是情境，拿不到就不寫
        label = ""
    # 跟每輪動態產生的回答語言提示一樣：用這一輪實際生效的分流，沒給才看後台設定。
    codes = languages or language_routes(project_id)
    names = "、".join(LANGUAGE_NAMES.get(code, code) for code in codes)
    parts = [f"專案：{label}。" if label else "", f"這個專案的使用者可能說：{names}。"]
    return "".join(parts)


def choose_transcript(
    project_id: str, interim: str, final: str, languages: list[str] | None = None,
) -> Verdict:
    """Return the transcript to send; the final unless Jev clearly prefers the interim."""
    from config import get_settings
    from core.jev_client import jev_available, jev_nouls

    interim, final = interim.strip(), final.strip()
    if not interim or _comparable(interim) == _comparable(final):
        return Verdict(final, "final", reason="same")
    if _script_intrusion(interim, final):
        return Verdict(interim, "interim", reason="script")
    cfg = get_settings()
    if not cfg.asr_final_judge_enabled or not jev_available():
        return Verdict(final, "final", reason="disabled")
    try:
        scores = jev_nouls(
            _project_context(project_id, languages),
            {"interim": _plausible(interim), "final": _plausible(final)},
            timeout=cfg.asr_final_judge_timeout_seconds,
            purpose="asr_final_judge",
        )
    except Exception as exc:  # noqa: BLE001 - 判斷失敗照定稿送
        logger.warning(json.dumps(
            {"event": "asr_final_judge_failed", "error_type": type(exc).__name__},
        ))
        return Verdict(final, "final", reason="error")
    if scores["interim"] - scores["final"] >= DECISION_MARGIN:
        return Verdict(interim, "interim", scores, "jev")
    return Verdict(final, "final", scores, "jev")

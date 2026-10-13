"""Ask Clef which kinds of personal data a message contains.

2026-10-13 以 52 句虛構中文句子比較：OpenAI Privacy Filter（CPU）抓到 19/25、
每句 3–4 秒，漏掉「民國75年3月14日」「我爸周文雄」與信用卡、健保卡號；Clef
25/25、每句約 0.85 秒，誤報 2/27（綽號、「林護理師」）。Clef 只回答有沒有，不標出
位置，所以這裡只偵測、不遮罩——原本也沒有遮罩。

先問一題「有沒有任何個資」，有才問是哪幾類：一次 7 題要 0.85 秒，總判斷一題
約 0.11 秒，同一批 52 句也是 25/25、誤報 0/27，而大部分訊息沒有個資。只問 Clef：Jev 與 OpenAI 是外部
服務，為了查個資把個資送出去正好相反。
"""

from __future__ import annotations

import logging
from threading import BoundedSemaphore

from config import get_settings
from core.decision_router import decide

logger = logging.getLogger(__name__)

# 類別名稱沿用原本的 OPF 標籤，後台的個資提醒與稽核紀錄不必跟著改。
PII_QUESTIONS: dict[str, tuple[str, str, str]] = {
    "private_person": (
        "這句話有沒有提到某個私人個人的真實姓名？醫師、護理師等職稱、稱謂或綽號不算。",
        "有完整的私人姓名",
        "沒有私人姓名，或只有職稱、稱謂、綽號、機構名",
    ),
    "private_phone": (
        "這句話有沒有私人電話或手機號碼？",
        "有具體的電話號碼",
        "沒有電話號碼，或只是在問客服、護理站的電話",
    ),
    "account_number": (
        "這句話有沒有身分證字號、居留證號、病歷號、健保卡號、信用卡號或銀行帳號這類個人識別號碼？",
        "有具體的個人識別號碼",
        "沒有，或只有產品型號、訂單編號、日期、叫號號碼",
    ),
    "private_address": (
        "這句話有沒有私人住址？",
        "有具體的私人住址",
        "沒有，或只是機構地點、行政區名稱",
    ),
    "private_email": (
        "這句話有沒有電子郵件地址？",
        "有電子郵件地址",
        "沒有",
    ),
    "private_date": (
        "這句話有沒有個人的出生日期？",
        "有具體的出生日期",
        "沒有，或只是年齡、預約或看診日期",
    ),
    "secret": (
        "這句話有沒有密碼、驗證碼或登入憑證？",
        "有密碼、驗證碼或憑證",
        "沒有",
    ),
}
_QUESTIONS = {
    category: {
        "type": "noul",
        "instructions": instructions,
        "criteria": {"true": yes, "false": no},
    }
    for category, (instructions, yes, no) in PII_QUESTIONS.items()
}
_GATE = {
    "has_pii": {
        "type": "noul",
        "instructions": "這句話有沒有包含任何可以識別特定個人的私人資料？",
        "criteria": {
            "true": "有私人的姓名、電話、身分證或病歷、健保卡、信用卡、銀行帳號等識別號碼、住址、Email、出生日期，或密碼、驗證碼",
            "false": "沒有；職稱、稱謂、綽號、機構名稱與地點、客服電話、產品型號、訂單編號、年齡、預約日期都不算",
        },
    },
}
_THRESHOLD = 0.5

_inflight: BoundedSemaphore | None = None
_inflight_size = 0


def _slot() -> BoundedSemaphore:
    global _inflight, _inflight_size
    size = max(1, int(get_settings().privacy_max_inflight))
    if _inflight is None or _inflight_size != size:
        _inflight, _inflight_size = BoundedSemaphore(size), size
    return _inflight


def detect_pii(text: str) -> dict[str, int] | None:
    """Return ``{category: 1}`` for each kind found, or None when skipped or failed.

    Clef 單卡每秒只處理 3–4 個請求、每輪決策也在用；同時在掃的已經滿了就跳過
    這句，不排隊搶卡。
    """
    if not text.strip():
        return {}
    slot = _slot()
    if not slot.acquire(blocking=False):
        return None
    try:
        if not _found(_ask(text, _GATE)).get("has_pii"):
            return {}
        found = _found(_ask(text, _QUESTIONS))
    except Exception as exc:  # noqa: BLE001 - 偵測失敗不影響對話
        logger.warning("[privacy] Clef PII check failed: %s", exc)
        return None
    finally:
        slot.release()
    # 總判斷說有、細項都沒過門檻時仍要提醒，不能當成沒有個資。
    return found or {"unclassified": 1}


def _ask(text: str, questions: dict[str, dict[str, object]]):
    return decide(
        {"message": text},
        questions,
        timeout=get_settings().privacy_clef_timeout_seconds,
        purpose="privacy",
        providers=frozenset({"clef"}),
    )


def _found(result) -> dict[str, int]:
    return {
        category: 1
        for category, answer in result.answers.items()
        if float(answer.get("noul", 0.0)) >= _THRESHOLD
    }

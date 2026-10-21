"""專案 ID 的保留別名："default" 代表部署的預設專案（``DEFAULT_PROJECT_ID``）。

Brain 端同一套規則在 ``infra.project_context.normalize_project_id``。Backend 要在
查授權與專案限制之前先換成正式 ID，否則授權查的是 "default"、Brain 讀的卻是
預設專案的資料，兩邊對不上。
"""

from __future__ import annotations

import re

from app.config import get_tts_config

DEFAULT_PROJECT_ALIAS = "default"
# 與 Brain 的 infra.project_context._PROJECT_ID_RE 相同；設錯值時兩邊都退回 "default"，
# 才不會授權查一個專案、Brain 讀另一個。
_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def default_project_id() -> str:
    """部署的預設專案；沒設定時就是 "default" 本身。"""
    configured = (get_tts_config().default_project_id or "").strip()
    if not configured or not _PROJECT_ID_RE.match(configured):
        return DEFAULT_PROJECT_ALIAS
    return configured


def canonical_project_id(project_id: str | None) -> str:
    """去頭尾空白，並把保留別名 "default" 換成預設專案；空值維持空字串。"""
    text = (project_id or "").strip()
    if text == DEFAULT_PROJECT_ALIAS:
        return default_project_id()
    return text

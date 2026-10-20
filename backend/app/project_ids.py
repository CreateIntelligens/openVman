"""專案 ID 的保留別名："default" 代表部署的預設專案（``DEFAULT_PROJECT_ID``）。

Brain 端同一套規則在 ``infra.project_context.normalize_project_id``。Backend 要在
查授權與專案限制之前先換成正式 ID，否則授權查的是 "default"、Brain 讀的卻是
預設專案的資料，兩邊對不上。
"""

from __future__ import annotations

from app.config import get_tts_config

DEFAULT_PROJECT_ALIAS = "default"


def default_project_id() -> str:
    """部署的預設專案；沒設定時就是 "default" 本身。"""
    configured = (get_tts_config().default_project_id or "").strip()
    return configured or DEFAULT_PROJECT_ALIAS


def canonical_project_id(project_id: str | None) -> str:
    """去頭尾空白，並把保留別名 "default" 換成預設專案；空值維持空字串。"""
    text = (project_id or "").strip()
    if text == DEFAULT_PROJECT_ALIAS:
        return default_project_id()
    return text

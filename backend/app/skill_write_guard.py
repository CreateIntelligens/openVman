"""Keep shared skills read-only in the admin and skill IDs safe to use as paths.

共用技能套用到所有專案，正式環境的 ``brain/skills`` 又是唯讀掛載，內容只能改 repo
再部署，所以後台對所有人都只能看；只有最高管理員能啟用或停用。Brain 不認得帳號，
在 Backend 轉給 Brain 之前擋。技能 ID 會變成 Brain 上的目錄與 Python 函式名稱，
規則與 Brain 的 ``tools.skill.SKILL_ID_PATTERN`` 相同。
"""

from __future__ import annotations

import json
import re

from fastapi import Request, status
from fastapi.responses import JSONResponse

from app.auth.dependencies import CurrentAccount
from app.auth.models import AccountRole
from app.project_ids import canonical_project_id

SKILL_ID_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
INVALID_SKILL_ID = "技能 ID 只能用英文字母、數字與底線（最多 64 字），而且不能以數字開頭"
SHARED_SKILL_READ_ONLY = (
    "共用技能套用到所有專案，內容要更新系統才能改，後台只能查看；"
    "最高管理員可以啟用或停用"
)
SHARED_SKILL_TOGGLE_ROOT_ONLY = "共用技能會套用到所有專案，只有最高管理員可以啟用或停用"
SHARED_SKILL_SCOPE_REQUIRED = "啟用或停用共用技能時要指定 scope=shared（只能一個）"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def is_skill_write(normalized_path: str, method: str) -> bool:
    method = method.upper()
    if method in _SAFE_METHODS or normalized_path.partition("/")[0] != "skills":
        return False
    # 重新載入只重讀磁碟上已有的檔案、不改內容，維持專案編輯權即可。
    return not (normalized_path == "skills/reload" and method == "POST")


def is_skill_toggle(normalized_path: str, method: str) -> bool:
    segments = normalized_path.split("/")
    return (
        method.upper() == "PATCH"
        and len(segments) == 3
        and segments[0] == "skills"
        and segments[2] == "toggle"
    )


def _refuse(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail})


def _create_payload(body: bytes) -> dict | None:
    # 建立技能的範圍只看 body。Brain 沒帶 Content-Type 也照 JSON 解析，
    # 這裡不能因為 header 不對就略過。
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _is_project_scoped(request: Request, payload: dict | None, normalized_path: str) -> bool:
    """Brain 沒指定範圍時會落到共用技能（建立預設 shared、其他路由在專案沒有
    同名技能時改用共用的），所以只有明確寫成 project 才算專案範圍。"""
    if normalized_path != "skills":
        return request.query_params.getlist("scope") == ["project"]
    return payload is not None and payload.get("scope") == "project"


def _shared_skill_refusal(
    request: Request,
    normalized_path: str,
    current: CurrentAccount | None,
) -> JSONResponse | None:
    if not is_skill_toggle(normalized_path, request.method):
        return _refuse(status.HTTP_403_FORBIDDEN, SHARED_SKILL_READ_ONLY)
    # 開關會影響所有專案，只給最高管理員；embed key 代表前台訪客，
    # 即使是 ROOT 建立的也不行。
    if (
        current is not None
        and current.embed_key is None
        and current.user.role is AccountRole.ROOT
    ):
        # 沒寫或重複的 scope 在這裡被當成共用放行，Brain 卻會先找同名的專案技能、
        # 或取最後一個值；放行的對象必須跟 Brain 實際切換的是同一個。
        if request.query_params.getlist("scope") != ["shared"]:
            return _refuse(status.HTTP_422_UNPROCESSABLE_ENTITY, SHARED_SKILL_SCOPE_REQUIRED)
        return None
    return _refuse(status.HTTP_403_FORBIDDEN, SHARED_SKILL_TOGGLE_ROOT_ONLY)


def skill_request_refusal(
    request: Request,
    normalized_path: str,
    body: bytes,
    current: CurrentAccount | None,
    project_id: str | None,
) -> JSONResponse | None:
    """Return the refusal for a skill request, or ``None`` to forward it."""
    segments = normalized_path.split("/")
    if segments[0] != "skills":
        return None

    payload = _create_payload(body) if normalized_path == "skills" else None
    if is_skill_write(normalized_path, request.method):
        # 共用技能先擋：不管 ID 寫成什麼，沒權限的人都該先知道「不能改」。
        if not _is_project_scoped(request, payload, normalized_path):
            refusal = _shared_skill_refusal(request, normalized_path, current)
            if refusal is not None:
                return refusal
        else:
            body_project_id = payload.get("project_id") if payload is not None else None
            if (
                isinstance(body_project_id, str)
                and canonical_project_id(body_project_id) != project_id
            ):
                # 授權查的是 query 的專案；body 指向別的專案時 Brain 會照 body 建立。
                return _refuse(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "project_id in query and body must match",
                )

    if len(segments) >= 2 and not SKILL_ID_PATTERN.fullmatch(segments[1]):
        return _refuse(status.HTTP_422_UNPROCESSABLE_ENTITY, INVALID_SKILL_ID)
    if payload is not None and is_skill_write(normalized_path, request.method):
        skill_id = payload.get("skill_id")
        if not isinstance(skill_id, str) or not SKILL_ID_PATTERN.fullmatch(skill_id):
            return _refuse(status.HTTP_422_UNPROCESSABLE_ENTITY, INVALID_SKILL_ID)
    return None

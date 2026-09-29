"""The caller's own ASR engine choice.

沒選過的人用部署設定的 ASR_PROVIDER（.env）。以前後台還有一個「全站預設引擎」
可以蓋過它，2026-09-24 拔掉：一個人的選擇不該由後台替所有人決定，要換引擎就
自己選（管理者在帳號頁決定每個帳號能選哪些）。

白名單一律在後端比對：前端送什麼都要對照管理者開放的清單，否則使用者改一
個請求就能繞過後台設定。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from app.config import get_tts_config

from .asr_selection import (
    asr_user_choices as _asr_user_choices,
    permitted_asr_preference,
)
from .dependencies import CurrentAccount, get_current_account
from .runtime import AuthRuntime, get_auth_runtime

settings_router = APIRouter(prefix="/api/v1/settings", tags=["Settings"])


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MyAsrProviderProfile(_StrictModel):
    """The caller's own engine choice."""

    # 空字串代表沒選過，用部署預設（effective 會是那個引擎）。
    value: str
    effective: str
    allowed: list[str]


class UpdateMyAsrProviderRequest(_StrictModel):
    value: str


@settings_router.get("/my-asr-provider", response_model=MyAsrProviderProfile)
def get_my_asr_provider(
    account: CurrentAccount = Depends(get_current_account),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> MyAsrProviderProfile:
    """Any signed-in user may read their own choice."""
    allowed = _asr_user_choices(runtime, account.user)
    stored = runtime.account_access.get_asr_provider(account.user.id)
    # 選過但之後被管理者關閉的引擎不該繼續生效，否則關閉形同虛設。
    effective = (
        permitted_asr_preference(runtime, account.user, stored)
        or get_tts_config().asr_provider
    )
    return MyAsrProviderProfile(
        value=stored, effective=effective, allowed=allowed,
    )


@settings_router.put("/my-asr-provider", response_model=MyAsrProviderProfile)
def set_my_asr_provider(
    body: UpdateMyAsrProviderRequest,
    account: CurrentAccount = Depends(get_current_account),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> MyAsrProviderProfile:
    """Pick an engine for this account's own chat.

    白名單在後端把關：前端送什麼都要對照管理者開放的清單，否則使用者改一
    個 API 請求就能繞過後台設定。空字串代表改回部署預設。
    """
    allowed = _asr_user_choices(runtime, account.user)
    if body.value and body.value not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"asr provider must be one of: {', '.join(allowed)}",
        )
    runtime.account_access.set_asr_provider(account.user.id, body.value)
    return get_my_asr_provider(account=account, runtime=runtime)

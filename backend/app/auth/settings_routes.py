"""The caller's own ASR engine choice and front-end settings.

前台設定（`/my-preferences`）跟著帳號存，換電腦、換瀏覽器也在；只收白名單內的欄位。

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


# 前台設定視窗能存的欄位，對應 frontend/app/src/stores/useSettingsStore.ts 的 SettingsState。
# 只收這些：這張表每個帳號都能寫，不能變成任意資料的儲存空間。
PREFERENCE_KEYS = frozenset({
    "ttsProvider", "characterId", "projectId", "personaId", "voiceMode",
    "ttsVoice", "backgroundId", "backgroundUrl", "backgroundFit",
    "cameraPreviewScale", "renderMode", "vrmAvatarId", "replyMode",
})
_PREFERENCE_VALUE_MAX_CHARS = 2048


class MyPreferences(_StrictModel):
    """Front-end settings saved for this account, keyed like the settings store."""

    values: dict[str, str]


def _shared_by_visitors(account: CurrentAccount) -> bool:
    # 嵌入金鑰是很多訪客共用一個帳號，存下來會把上一位訪客的選擇帶給下一位。
    # 不回 403：前台遇到 403 會把整頁換成「權限不足」，這裡只是不存而已。
    return account.embed_key is not None


@settings_router.get("/my-preferences", response_model=MyPreferences)
def get_my_preferences(
    account: CurrentAccount = Depends(get_current_account),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> MyPreferences:
    """Settings this account saved on any device."""
    if _shared_by_visitors(account):
        return MyPreferences(values={})
    stored = runtime.account_access.get_preferences(account.user.id)
    # 白名單縮過的欄位可能還留在舊資料裡，回傳時一併濾掉。
    return MyPreferences(values={
        key: str(value) for key, value in stored.items() if key in PREFERENCE_KEYS
    })


@settings_router.put("/my-preferences", response_model=MyPreferences)
def update_my_preferences(
    body: MyPreferences,
    account: CurrentAccount = Depends(get_current_account),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> MyPreferences:
    """Merge the fields the user just applied; fields not sent are kept."""
    if _shared_by_visitors(account):
        return MyPreferences(values={})
    unknown = sorted(set(body.values) - PREFERENCE_KEYS)
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown preference keys: {', '.join(unknown)}")
    too_long = sorted(k for k, v in body.values.items() if len(v) > _PREFERENCE_VALUE_MAX_CHARS)
    if too_long:
        raise HTTPException(status_code=422, detail=f"preference values too long: {', '.join(too_long)}")
    merged = runtime.account_access.merge_preferences(account.user.id, body.values)
    return MyPreferences(values={
        key: str(value) for key, value in merged.items() if key in PREFERENCE_KEYS
    })

"""Runtime ASR settings: the site default and what users may pick.

從 routes.py 搬出來的，行為未改。這一組端點管兩件事：全站預設用哪個引擎
（限 ROOT），以及開放哪些引擎讓一般使用者替自己的對話選。

白名單一律在後端比對：前端送什麼都要對照管理者開放的清單，否則使用者改一
個請求就能繞過後台設定。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from app.config import get_tts_config

from .dependencies import (
    CurrentAccount,
    get_current_account,
    require_admin,
    require_root,
)
from .runtime import AuthRuntime, get_auth_runtime
from .settings_repository import (
    ASR_PROVIDER_KEY,
    ASR_USER_CHOICES_KEY,
    BROWSER_ASR_PROVIDER,
    SERVER_ASR_PROVIDERS,
    InvalidSettingValueError,
    UnknownSettingError,
)

settings_router = APIRouter(prefix="/api/v1/settings", tags=["Settings"])


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SystemSettingProfile(_StrictModel):
    key: str
    value: str
    # 目前生效的值：沒有覆寫時等於環境變數的預設。前端要能分辨「沒設定」
    # 與「設成跟預設一樣」，否則清除按鈕沒有意義。
    effective: str
    overridden: bool
    options: list[str]


class UpdateSystemSettingRequest(_StrictModel):
    value: str


def _asr_setting_profile(runtime: AuthRuntime) -> SystemSettingProfile:
    stored = runtime.settings.get(ASR_PROVIDER_KEY)
    default = get_tts_config().asr_provider
    return SystemSettingProfile(
        key=ASR_PROVIDER_KEY,
        value=stored or "",
        effective=stored or default,
        overridden=stored is not None,
        options=sorted(runtime.settings.allowed_values(ASR_PROVIDER_KEY)),
    )


@settings_router.get("/asr-provider", response_model=SystemSettingProfile)
def get_asr_provider(
    _admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> SystemSettingProfile:
    return _asr_setting_profile(runtime)


@settings_router.put("/asr-provider", response_model=SystemSettingProfile)
def set_asr_provider(
    body: UpdateSystemSettingRequest,
    root: CurrentAccount = Depends(require_root),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> SystemSettingProfile:
    """Override which ASR engine every request uses.

    限 ROOT：這個設定影響每一個使用者的每一次語音輸入，而且改錯了要到下一
    次有人講話才會發現。
    """
    try:
        runtime.settings.set(ASR_PROVIDER_KEY, body.value, actor_id=root.user.id)
    except InvalidSettingValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except UnknownSettingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _asr_setting_profile(runtime)


@settings_router.delete("/asr-provider", response_model=SystemSettingProfile)
def clear_asr_provider(
    root: CurrentAccount = Depends(require_root),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> SystemSettingProfile:
    """Drop the override so the environment default applies again."""
    runtime.settings.clear(ASR_PROVIDER_KEY, actor_id=root.user.id)
    return _asr_setting_profile(runtime)


class AsrUserChoicesProfile(_StrictModel):
    """Which engines an ordinary user may pick for their own chat."""

    allowed: list[str]
    options: list[str]
    overridden: bool


class UpdateAsrUserChoicesRequest(_StrictModel):
    allowed: list[str]


class MyAsrProviderProfile(_StrictModel):
    """The caller's own engine choice."""

    # 空字串代表沒選過，沿用全站設定。
    value: str
    effective: str
    allowed: list[str]


class UpdateMyAsrProviderRequest(_StrictModel):
    value: str


# 預設全部開放：管理者要縮小範圍再自己關。開放清單是「誰能選」，不是
# 「用哪個」——後者仍由 asr_provider 與各使用者的選擇決定。
_DEFAULT_USER_CHOICES = sorted(SERVER_ASR_PROVIDERS | {BROWSER_ASR_PROVIDER})


def _asr_user_choices(runtime: AuthRuntime) -> list[str]:
    stored = runtime.settings.get_many(ASR_USER_CHOICES_KEY)
    return _DEFAULT_USER_CHOICES if stored is None else stored


def _asr_user_choices_profile(runtime: AuthRuntime) -> AsrUserChoicesProfile:
    stored = runtime.settings.get_many(ASR_USER_CHOICES_KEY)
    return AsrUserChoicesProfile(
        allowed=_DEFAULT_USER_CHOICES if stored is None else stored,
        options=_DEFAULT_USER_CHOICES,
        overridden=stored is not None,
    )


@settings_router.get("/asr-user-choices", response_model=AsrUserChoicesProfile)
def get_asr_user_choices(
    _admin: CurrentAccount = Depends(require_admin),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> AsrUserChoicesProfile:
    return _asr_user_choices_profile(runtime)


@settings_router.put("/asr-user-choices", response_model=AsrUserChoicesProfile)
def set_asr_user_choices(
    body: UpdateAsrUserChoicesRequest,
    root: CurrentAccount = Depends(require_root),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> AsrUserChoicesProfile:
    """Choose which engines ordinary users may select.

    限 ROOT：開放 openai 等於允許每個使用者自行把語音送往外部服務，那是
    組織層級的決定，不該讓一般管理者順手改掉。
    """
    try:
        runtime.settings.set_many(
            ASR_USER_CHOICES_KEY, body.allowed, actor_id=root.user.id,
        )
    except InvalidSettingValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except UnknownSettingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _asr_user_choices_profile(runtime)


@settings_router.get("/my-asr-provider", response_model=MyAsrProviderProfile)
def get_my_asr_provider(
    account: CurrentAccount = Depends(get_current_account),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> MyAsrProviderProfile:
    """Any signed-in user may read their own choice."""
    allowed = _asr_user_choices(runtime)
    stored = runtime.account_access.get_asr_provider(account.user.id)
    site_default = runtime.settings.get(ASR_PROVIDER_KEY) or ""
    # 選過但之後被管理者關閉的引擎不該繼續生效，否則關閉形同虛設。
    effective = stored if stored in allowed else (site_default or "")
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
    個 API 請求就能繞過後台設定。空字串代表改回沿用全站設定。
    """
    allowed = _asr_user_choices(runtime)
    if body.value and body.value not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"asr provider must be one of: {', '.join(allowed)}",
        )
    runtime.account_access.set_asr_provider(account.user.id, body.value)
    return get_my_asr_provider(account=account, runtime=runtime)

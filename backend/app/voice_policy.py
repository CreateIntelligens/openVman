"""What one voice request may use: account grants narrowed by its project policy.

帳號授權決定「這個人能用什麼」，專案限制決定「這個專案肯用什麼」，實際能用的是
兩者交集。專案沒有設定（或清單是空的）時完全照舊，所以這裡每個函式在
``policy is None`` 或不限制時都必須回到改版前的結果。

Embed key 沒有帳號授權：專案有限制時以專案清單代替帳號授權（金鑰綁定專案，
專案清單就是管理者替這個專案開的範圍）；不限制時照舊，只能用部署預設。
"""

from __future__ import annotations

from dataclasses import dataclass

from app import language_routes as language_routes_mod
from app.auth.asr_selection import asr_user_choices, permitted_asr_preference
from app.auth.dependencies import CurrentAccount
from app.auth.models import (
    AccountRole,
    ProjectPolicyRecord,
    ResourceType,
    UserRecord,
)
from app.auth.project_resources import effective_project_resources
from app.auth.runtime import AuthRuntime
from app.auth.settings_repository import SERVER_ASR_PROVIDERS
from app.config import get_tts_config


def project_policy(
    runtime: AuthRuntime,
    project_id: str | None,
) -> ProjectPolicyRecord | None:
    """The stored policy for an already-authorized project, or None without one."""
    if not project_id:
        return None
    return runtime.project_policies.get(project_id)


def request_policy(
    runtime: AuthRuntime,
    current: CurrentAccount,
    supplied_project_id: str,
) -> tuple[str | None, ProjectPolicyRecord | None]:
    """Resolve the caller's project (an embed key's own) and its policy."""
    project_id = language_routes_mod.resolve_project(current, supplied_project_id)
    return project_id, project_policy(runtime, project_id)


@dataclass(frozen=True, slots=True)
class BatchAsrScope:
    """Batch ASR limits for one request."""

    # 單次請求明確指定 provider 時可以點名的引擎（帳號授權 ∩ 專案清單 ∪ 專案資源 ∪ ROOT 指派）。
    explicit: frozenset[str]
    # 每一次嘗試（含備援）可以用的引擎；部署預設只有專案允許時才算在內。
    allowed: frozenset[str]
    # 沒指定 provider 時優先嘗試的引擎。
    preferred: str | None
    # 台語分流要強制使用的引擎；None 代表不換，照 preferred。
    taiwanese: str | None


def batch_asr_scope(
    runtime: AuthRuntime,
    user: UserRecord | None,
    policy: ProjectPolicyRecord | None,
    *,
    embed: bool = False,
    project_id: str | None = None,
) -> BatchAsrScope:
    """Compute the batch ASR scope for an account (or embed key) and project."""
    cfg = get_tts_config()
    p_id = (policy.project_id if policy is not None else None) or project_id
    assigned_or_project_asr: set[str] = set()
    if p_id:
        assigned_or_project_asr = {
            e.resource_id
            for e in effective_project_resources(
                runtime,
                None if embed or user is None else user,
                p_id,
                ResourceType.ASR_ENGINE,
            )
            if e.source in ("project", "assigned")
        }

    if embed or user is None:
        granted = (
            set(policy.allowed_asr_engines)
            if policy is not None and policy.restricts_asr else set()
        )
        preference = ""
    else:
        granted = set(asr_user_choices(runtime, user))
        preference = permitted_asr_preference(
            runtime, user, runtime.account_access.get_asr_provider(user.id),
        )
    is_root = not embed and user is not None and user.role is AccountRole.ROOT
    implicit = granted | {cfg.asr_provider} | assigned_or_project_asr
    if is_root or policy is None:
        allowed = implicit
        explicit = granted | assigned_or_project_asr
    else:
        allowed = policy.narrow_asr(implicit) | assigned_or_project_asr
        explicit = policy.narrow_asr(granted) | assigned_or_project_asr

    # 偏好 → 專案預設 → 部署預設；每一個都要落在 allowed 裡才算數。
    candidates = (
        preference,
        policy.default_asr_engine if policy is not None else None,
        cfg.asr_provider,
    )
    preferred = next(
        (
            engine for engine in candidates
            if engine and engine in allowed and engine in SERVER_ASR_PROVIDERS
        ),
        None,
    )

    configured_taiwanese = policy.taiwanese_asr_engine if policy is not None else None
    taiwanese: str | None = (
        configured_taiwanese or language_routes_mod.TAIWANESE_ASR_ENGINE
    )
    # 沒設專案限制也沒指定台語引擎時維持舊行為（一律 Breeze，備援清單會濾掉沒授權的）；
    # 一旦專案有意見，台語引擎也得落在允許範圍內，否則就不強制換引擎。ROOT 豁免專案限制。
    if (
        not is_root
        and (configured_taiwanese or (policy is not None and policy.restricts_asr))
        and taiwanese not in allowed
    ):
        taiwanese = None
    return BatchAsrScope(
        explicit=frozenset(explicit),
        allowed=frozenset(allowed),
        preferred=preferred,
        taiwanese=taiwanese,
    )


def effective_asr_engine(
    runtime: AuthRuntime,
    user: UserRecord,
    policy: ProjectPolicyRecord | None,
    *,
    project_id: str | None = None,
) -> str:
    """The engine a client should start with in this project ("" when none is allowed)."""
    cfg = get_tts_config()
    granted = set(asr_user_choices(runtime, user))
    preference = permitted_asr_preference(
        runtime, user, runtime.account_access.get_asr_provider(user.id),
    )
    p_id = (policy.project_id if policy is not None else None) or project_id
    assigned_or_project_asr: set[str] = set()
    if p_id:
        assigned_or_project_asr = {
            e.resource_id
            for e in effective_project_resources(
                runtime, user, p_id, ResourceType.ASR_ENGINE
            )
            if e.source in ("project", "assigned")
        }
        granted = granted | assigned_or_project_asr

    is_root = user.role is AccountRole.ROOT
    if policy is None:
        if preference and (preference in granted or preference == cfg.asr_provider):
            return preference
        return cfg.asr_provider
    candidates = (
        (preference, preference in granted),
        (policy.default_asr_engine, policy.default_asr_engine in granted),
        (cfg.asr_provider, True),
    )
    for engine, permitted in candidates:
        if engine and permitted and (
            is_root or policy.allows_asr(engine) or engine in assigned_or_project_asr
        ):
            return engine
    return ""

"""Central actor/target policy for account administration."""

from __future__ import annotations

from .models import AccountRole, AccountType, UserRecord, is_at_least_admin


class AccountPolicyError(PermissionError):
    pass


def ensure_account_manager(actor: UserRecord) -> None:
    if (
        actor.disabled
        or actor.account_type is not AccountType.FORMAL
        or not is_at_least_admin(actor.role)
    ):
        raise AccountPolicyError("administrator access required")


def ensure_can_create_role(actor: UserRecord, role: AccountRole) -> None:
    ensure_account_manager(actor)
    if role is AccountRole.ROOT:
        raise AccountPolicyError("ROOT accounts cannot be created")


def ensure_can_manage_account(actor: UserRecord, target: UserRecord) -> None:
    ensure_account_manager(actor)
    if target.role is AccountRole.ROOT:
        raise AccountPolicyError("ROOT cannot be changed through account administration")
    if actor.role is AccountRole.ROOT:
        return
    if target.id == actor.id:
        raise AccountPolicyError(
            "administrators cannot manage their own account here"
        )
    # admin 管得到自己建立的帳號，含自己開出來的 admin——委派鏈上每一層的
    # 範圍都只會更窄（資源指派受 _assert_grants_within_scope 收斂）。但只限
    # 直屬下一層：放行整棵子樹的話，被降權的中間人仍能繞過去改孫節點。
    if target.created_by != actor.id:
        raise AccountPolicyError(
            "administrators can only manage accounts they created"
        )


def ensure_can_change_role(
    actor: UserRecord,
    target: UserRecord,
    role: AccountRole,
) -> None:
    ensure_can_manage_account(actor, target)
    if actor.role is not AccountRole.ROOT:
        raise AccountPolicyError("only ROOT can change account roles")
    if role is AccountRole.ROOT:
        raise AccountPolicyError("ROOT role cannot be assigned")
    if target.account_type is not AccountType.FORMAL:
        raise AccountPolicyError("temporary account roles cannot be changed")


def ensure_can_reset_password(actor: UserRecord, target: UserRecord) -> None:
    ensure_can_manage_account(actor, target)
    if actor.role is not AccountRole.ROOT:
        raise AccountPolicyError("only ROOT can reset account passwords")
    if target.account_type is not AccountType.FORMAL:
        raise AccountPolicyError("temporary account passwords cannot be reset")

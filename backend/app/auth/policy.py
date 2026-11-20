"""Central actor/target policy for account administration."""

from __future__ import annotations

from .models import (
    AccountRole,
    AccountType,
    UserRecord,
    has_web_search_access,
    is_at_least_admin,
)


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


def is_vendor_account(user: UserRecord) -> bool:
    return (
        user.account_type is AccountType.FORMAL
        and user.role is AccountRole.USER
        and bool(user.vendor_name)
    )


def can_manage_vendor_accounts(actor: UserRecord) -> bool:
    return actor.role is AccountRole.ROOT or (
        actor.role is AccountRole.ADMIN and actor.account_management_access
    )


def ensure_can_grant_web_search(actor: UserRecord, requested: bool | None) -> None:
    """Only an account that may search the web can turn it on for another account or key."""
    # 委派鏈上每一層的範圍只會更窄：自己被關掉的人，開子帳號或嵌入金鑰也拿不回來。
    if requested and not has_web_search_access(actor):
        raise AccountPolicyError("你的帳號沒有網路搜尋權限，不能替其他帳號或嵌入金鑰開啟。")


def ensure_can_grant_account_management(actor: UserRecord) -> None:
    ensure_account_manager(actor)
    if actor.role is not AccountRole.ROOT:
        raise AccountPolicyError("only ROOT can grant account management access")


def ensure_can_manage_account(
    actor: UserRecord,
    target: UserRecord,
    *,
    cross_creator_vendor: bool = False,
) -> None:
    ensure_account_manager(actor)
    if target.role is AccountRole.ROOT:
        raise AccountPolicyError("ROOT cannot be changed through account administration")
    if actor.role is AccountRole.ROOT:
        return
    if target.id == actor.id:
        raise AccountPolicyError(
            "administrators cannot manage their own account here"
        )
    if is_vendor_account(target):
        if not can_manage_vendor_accounts(actor):
            raise AccountPolicyError("vendor account management access required")
        if cross_creator_vendor:
            return
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
    if role is not AccountRole.USER and is_vendor_account(target):
        raise AccountPolicyError("clear vendor affiliation before changing the role")


def ensure_can_reset_password(actor: UserRecord, target: UserRecord) -> None:
    ensure_can_manage_account(actor, target, cross_creator_vendor=True)
    if actor.role is not AccountRole.ROOT and not is_vendor_account(target):
        raise AccountPolicyError("password reset requires ROOT or vendor account management")
    if target.account_type is not AccountType.FORMAL:
        raise AccountPolicyError("temporary account passwords cannot be reset")

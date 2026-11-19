"""Changing an account's vendor revokes its API keys as well as its login sessions."""

from __future__ import annotations

import pytest

from app.auth.api_keys_repository import InvalidApiKeyError
from app.auth.models import AccountRole, ResourceType
from app.auth.runtime import build_auth_runtime
from app.config import TTSRouterConfig


def _runtime(tmp_path):
    return build_auth_runtime(TTSRouterConfig(
        _env_file=None, env="dev", session_jwt_secret="x" * 40,
        auth_database_path=str(tmp_path / "auth.db"),
    ))


def _vendor_account(rt):
    root = rt.users.create_root(username="ai360", password_hash="unused")
    for resource_type, resource_id in (
        (ResourceType.PROJECT, "p1"),
        (ResourceType.AVATAR_CHARACTER, "a1"),
        (ResourceType.CUSTOM_VOICE, "v1"),
    ):
        rt.resources.upsert_system_resource(resource_type=resource_type, resource_id=resource_id)
    rt.resources.set_project_vendor("p1", "acme")
    user = rt.users.create(
        username="vendor-user", password_hash="unused", role=AccountRole.USER,
        created_by=root.id, vendor_name="acme",
        grants=[(ResourceType.PROJECT, "p1"), (ResourceType.AVATAR_CHARACTER, "a1"), (ResourceType.CUSTOM_VOICE, "v1")],
        defaults=("p1", "a1", "indextts", "v1"),
    )
    return root, user


@pytest.mark.parametrize("new_vendor", ["other", None])
def test_changing_vendor_revokes_existing_api_keys(tmp_path, new_vendor):
    rt = _runtime(tmp_path)
    root, user = _vendor_account(rt)
    _, secret = rt.api_keys.create(actor_id=root.id, user_id=user.id, label="k")
    rt.api_keys.authenticate(secret)

    rt.users.set_vendor_affiliation(actor_id=root.id, user_id=user.id, vendor_name=new_vendor)

    with pytest.raises(InvalidApiKeyError):
        rt.api_keys.authenticate(secret)


def test_setting_the_same_vendor_keeps_api_keys(tmp_path):
    rt = _runtime(tmp_path)
    root, user = _vendor_account(rt)
    _, secret = rt.api_keys.create(actor_id=root.id, user_id=user.id, label="k")

    rt.users.set_vendor_affiliation(actor_id=root.id, user_id=user.id, vendor_name="acme")

    rt.api_keys.authenticate(secret)

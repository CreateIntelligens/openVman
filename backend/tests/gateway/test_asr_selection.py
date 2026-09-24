"""Queued audio jobs must recheck preferences after grants change."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.auth.models import AccountRole, AccountType, ResourceType
from app.auth.settings_routes import get_my_asr_provider
from app.gateway.worker import _account_asr_provider


@pytest.fixture
def runtime(monkeypatch):
    runtime = SimpleNamespace(
        users=Mock(), account_access=Mock(), resources=Mock(), settings=Mock(),
    )
    runtime.account_access.get_asr_provider.return_value = "openai"
    runtime.settings.get.return_value = "sensevoice"
    runtime.resources.list_by_type.return_value = [
        SimpleNamespace(resource_id="openai"),
    ]
    monkeypatch.setattr("app.auth.runtime.get_auth_runtime", lambda: runtime)
    return runtime


@pytest.mark.parametrize("account_type", list(AccountType))
def test_worker_rechecks_revoked_asr_preference(runtime, account_type):
    user = SimpleNamespace(
        id="owner", role=AccountRole.USER, account_type=account_type,
    )
    runtime.users.get_by_id.return_value = user
    runtime.account_access.list_grants.return_value = [
        SimpleNamespace(
            resource_type=ResourceType.ASR_ENGINE, resource_id="openai",
        ),
    ]
    queued_job = {"owner_user_id": user.id}
    assert _account_asr_provider(queued_job) == "openai"

    runtime.account_access.list_grants.return_value = []
    profile = get_my_asr_provider(
        account=SimpleNamespace(user=user), runtime=runtime,
    )
    assert profile.value == "openai"
    assert profile.effective == "sensevoice"
    assert _account_asr_provider(queued_job) is None


def test_root_keeps_registered_engine_without_grants(runtime):
    runtime.users.get_by_id.return_value = SimpleNamespace(
        id="root", role=AccountRole.ROOT,
    )
    runtime.account_access.list_grants.return_value = []
    assert _account_asr_provider({"owner_user_id": "root"}) == "openai"
    runtime.resources.list_by_type.return_value = []
    assert _account_asr_provider({"owner_user_id": "root"}) is None


def test_missing_owner_falls_back_to_site_default(runtime):
    assert _account_asr_provider({}) is None
    runtime.users.get_by_id.return_value = None
    assert _account_asr_provider({"owner_user_id": "deleted"}) is None
    runtime.account_access.get_asr_provider.assert_not_called()

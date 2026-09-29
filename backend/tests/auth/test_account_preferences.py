"""Front-end settings follow the account across devices."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.auth.database import AuthDatabase
from app.auth.models import AccountRole
from app.auth.repositories import AccountAccessRepository, UserRepository
from app.auth.settings_routes import (
    MyPreferences,
    get_my_preferences,
    update_my_preferences,
)


@pytest.fixture()
def setup(tmp_path: Path):
    database = AuthDatabase(tmp_path / "accounts.db")
    database.initialize()
    user = UserRepository(database).create(
        username="kiosk", password_hash="hash", role=AccountRole.USER,
    )
    runtime = SimpleNamespace(account_access=AccountAccessRepository(database))
    account = SimpleNamespace(user=user, embed_key=None)
    return runtime, account


def test_nothing_saved_yet_returns_empty(setup):
    runtime, account = setup
    assert get_my_preferences(account=account, runtime=runtime).values == {}


def test_saving_merges_so_another_device_keeps_other_fields(setup):
    runtime, account = setup
    update_my_preferences(
        MyPreferences(values={"projectId": "proj-a", "ttsProvider": "voxcpm"}),
        account=account, runtime=runtime,
    )
    # 另一台只改了背景，不能把專案與聲音洗掉。
    merged = update_my_preferences(
        MyPreferences(values={"backgroundId": "light"}),
        account=account, runtime=runtime,
    ).values
    assert merged == {"projectId": "proj-a", "ttsProvider": "voxcpm", "backgroundId": "light"}
    assert get_my_preferences(account=account, runtime=runtime).values == merged


def test_unknown_keys_and_huge_values_are_rejected(setup):
    runtime, account = setup
    with pytest.raises(HTTPException) as unknown:
        update_my_preferences(
            MyPreferences(values={"anything": "x"}), account=account, runtime=runtime,
        )
    assert unknown.value.status_code == 422
    with pytest.raises(HTTPException) as huge:
        update_my_preferences(
            MyPreferences(values={"backgroundUrl": "x" * 5000}), account=account, runtime=runtime,
        )
    assert huge.value.status_code == 422
    assert get_my_preferences(account=account, runtime=runtime).values == {}


def test_embed_keys_neither_read_nor_save(setup):
    runtime, account = setup
    update_my_preferences(
        MyPreferences(values={"projectId": "mine"}), account=account, runtime=runtime,
    )
    shared = SimpleNamespace(user=account.user, embed_key=SimpleNamespace(project_id="p"))
    assert get_my_preferences(account=shared, runtime=runtime).values == {}
    update_my_preferences(
        MyPreferences(values={"projectId": "visitor"}), account=shared, runtime=runtime,
    )
    assert get_my_preferences(account=account, runtime=runtime).values == {"projectId": "mine"}


def test_whitelist_matches_the_front_end_settings_store():
    """前台加了設定欄位卻沒加進白名單，存到帳號時會整批 422。"""
    import re

    from app.auth.settings_routes import PREFERENCE_KEYS

    store = Path(__file__).resolve().parents[3] / "frontend/app/src/stores/useSettingsStore.ts"
    if not store.exists():
        pytest.skip("frontend source not available")
    block = re.search(r"const PREF_KEYS[^{]*\{(.*?)\n\}", store.read_text(encoding="utf-8"), re.S)
    assert block, "PREF_KEYS not found in useSettingsStore.ts"
    front_end_fields = set(re.findall(r"^\s*(\w+):", block.group(1), re.M))
    assert front_end_fields == set(PREFERENCE_KEYS)

import pytest

from app.avatar.mascot_store import (
    BUILTIN_MASCOTS,
    MascotExists,
    MascotNotFound,
    MascotStore,
)


@pytest.fixture
def store(tmp_path):
    return MascotStore(base_dir=tmp_path)


def _make_mascot(store, mascot_id="custom", label="自訂小助理"):
    return store.create_mascot(
        mascot_id=mascot_id,
        label=label,
        vrm_bytes=b"glTFvrm",
    )


def test_list_includes_builtin_mascots(store):
    mascots = store.list_mascots()

    assert [mascot["mascot_id"] for mascot in mascots[:3]] == [
        mascot["mascot_id"] for mascot in BUILTIN_MASCOTS
    ]
    assert mascots[1]["label"] == "Frieren"
    assert mascots[1]["builtin"] is True


def test_create_uploaded_mascot(store):
    mascot = _make_mascot(store)

    assert mascot["mascot_id"] == "custom"
    assert mascot["label"] == "自訂小助理"
    assert mascot["engine"] == "3d"
    assert mascot["vrm_url"] == "/mascots/custom/model.vrm"
    assert mascot["builtin"] is False


def test_create_duplicate_uploaded_raises(store):
    _make_mascot(store)

    with pytest.raises(MascotExists):
        _make_mascot(store)


def test_create_duplicate_builtin_raises(store):
    with pytest.raises(MascotExists):
        _make_mascot(store, mascot_id="qqman")


def test_update_uploaded_label(store):
    _make_mascot(store)
    updated = store.update_label("custom", "新名稱")

    assert updated["mascot_id"] == "custom"
    assert updated["label"] == "新名稱"


def test_update_builtin_label_raises(store):
    with pytest.raises(MascotNotFound):
        store.update_label("qqman", "新名稱")


def test_delete_uploaded_mascot(store):
    _make_mascot(store)
    store.delete_mascot("custom")

    assert [mascot["mascot_id"] for mascot in store.list_mascots()] == [
        mascot["mascot_id"] for mascot in BUILTIN_MASCOTS
    ]


def test_delete_builtin_raises(store):
    with pytest.raises(MascotNotFound):
        store.delete_mascot("qqman")

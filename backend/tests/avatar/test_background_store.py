import pytest

from app.avatar.background_store import (
    AvatarBackgroundStore,
    BackgroundExists,
    BackgroundNotFound,
)


@pytest.fixture
def store(tmp_path):
    return AvatarBackgroundStore(base_dir=tmp_path)


def _make_background(store, background_id="clinic", label="診間背景"):
    return store.create_background(
        background_id=background_id,
        label=label,
        image_bytes=b"\x89PNG\r\n\x1a\nimage",
        filename="clinic.png",
    )


def test_list_empty(store):
    assert store.list_backgrounds() == []


def test_create_then_list(store):
    created = _make_background(store)
    backgrounds = store.list_backgrounds()

    assert backgrounds == [created]
    assert created["background_id"] == "clinic"
    assert created["label"] == "診間背景"
    assert created["url"] == "/backgrounds/clinic/image.png"
    assert created["mime_type"] == "image/png"
    assert created["size_bytes"] > 0
    assert "updated_at" in created


def test_create_writes_files(store, tmp_path):
    _make_background(store)
    background_dir = tmp_path / "clinic"

    assert (background_dir / "image.png").read_bytes() == b"\x89PNG\r\n\x1a\nimage"
    assert (background_dir / "meta.json").exists()


def test_create_duplicate_raises(store):
    _make_background(store)

    with pytest.raises(BackgroundExists):
        _make_background(store)


def test_update_label_keeps_background_id(store):
    _make_background(store)
    updated = store.update_label("clinic", "新的診間")

    assert updated["background_id"] == "clinic"
    assert updated["label"] == "新的診間"
    assert store.get_background("clinic")["label"] == "新的診間"


def test_delete(store):
    _make_background(store)
    store.delete_background("clinic")

    assert store.list_backgrounds() == []


def test_delete_missing_raises(store):
    with pytest.raises(BackgroundNotFound):
        store.delete_background("missing")

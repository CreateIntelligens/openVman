import pytest

from app.avatar.store import (
    AvatarStore,
    CharacterExists,
    CharacterNotFound,
)


@pytest.fixture
def store(tmp_path):
    return AvatarStore(base_dir=tmp_path)


def _make_char(store, char_id="008", label="角色八"):
    store.create_character(
        char_id=char_id,
        label=label,
        video_bytes=b"\x1a\x45\xdf\xa3video",
        data_bytes=b"\x1f\x8bdata",
    )


def test_list_empty(store):
    assert store.list_characters() == []


def test_create_then_list(store):
    _make_char(store)
    chars = store.list_characters()
    assert len(chars) == 1
    c = chars[0]
    assert c["char_id"] == "008"
    assert c["label"] == "角色八"
    assert c["has_video"] is True
    assert c["has_data"] is True
    assert c["size_bytes"] > 0
    assert "updated_at" in c


def test_create_writes_files(store, tmp_path):
    _make_char(store)
    d = tmp_path / "008"
    assert (d / "01.webm").read_bytes() == b"\x1a\x45\xdf\xa3video"
    assert (d / "combined_data.json.gz").read_bytes() == b"\x1f\x8bdata"
    assert (d / "meta.json").exists()


def test_create_duplicate_raises(store):
    _make_char(store)
    with pytest.raises(CharacterExists):
        _make_char(store)


def test_delete(store):
    _make_char(store)
    store.delete_character("008")
    assert store.list_characters() == []


def test_delete_missing_raises(store):
    with pytest.raises(CharacterNotFound):
        store.delete_character("nope")


def test_rename(store):
    _make_char(store, char_id="008")
    store.rename_character("008", "008b")
    ids = [c["char_id"] for c in store.list_characters()]
    assert ids == ["008b"]


def test_update_label_keeps_character_id(store):
    _make_char(store, char_id="008", label="角色八")
    updated = store.update_label("008", "新的名字")
    assert updated["char_id"] == "008"
    assert updated["label"] == "新的名字"
    assert store.get_character("008")["label"] == "新的名字"


def test_rename_missing_raises(store):
    with pytest.raises(CharacterNotFound):
        store.rename_character("nope", "x")


def test_rename_to_existing_raises(store):
    _make_char(store, char_id="008")
    _make_char(store, char_id="009")
    with pytest.raises(CharacterExists):
        store.rename_character("008", "009")


def test_exists(store):
    assert store.exists("008") is False
    _make_char(store)
    assert store.exists("008") is True

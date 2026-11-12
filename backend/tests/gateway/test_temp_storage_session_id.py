import pytest

from app.avatar.validation import InvalidCharId, normalize_char_id
from app.gateway.temp_storage import TempStorageService as TempStorage


@pytest.mark.parametrize("session_id", ["", ".", "..", "../x", "a/b", "a\\b", "x" * 129, "a\x00b"])
def test_temp_storage_rejects_unsafe_session_ids(tmp_path, session_id):
    storage = TempStorage(base_dir=str(tmp_path))
    with pytest.raises(ValueError):
        storage.write_file(session_id, b"data", "image/png")
    assert list(tmp_path.iterdir()) == []


def test_cleanup_with_empty_session_id_keeps_the_root(tmp_path):
    # 舊的黑名單放行空字串，cleanup_session("") 會整個刪掉暫存根目錄。
    storage = TempStorage(base_dir=str(tmp_path))
    kept = storage.write_file("6917d92d-dd41-4579-8c6d-299056486cb7", b"data", "image/png")
    storage.cleanup_session("")
    assert tmp_path.exists()
    assert (tmp_path / "6917d92d-dd41-4579-8c6d-299056486cb7").exists()
    assert kept


@pytest.mark.parametrize("char_id", [".hidden", "...", "-x", "_x"])
def test_character_ids_must_start_with_a_letter_or_digit(char_id):
    with pytest.raises(InvalidCharId):
        normalize_char_id(char_id)


def test_existing_character_id_shapes_still_pass():
    for char_id in ("009", "0616", "dev-123", "hciot-motion", "heji_test_alpha", "local_aikka_aws"):
        assert normalize_char_id(char_id) == char_id

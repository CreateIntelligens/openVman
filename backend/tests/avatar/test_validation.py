import pytest

from app.avatar.validation import (
    InvalidCharId,
    InvalidUpload,
    normalize_char_id,
    validate_video_bytes,
    validate_data_bytes,
)


def test_normalize_char_id_accepts_valid():
    assert normalize_char_id("008") == "008"
    assert normalize_char_id("char.A-1_x") == "char.A-1_x"


@pytest.mark.parametrize("bad", ["", "a/b", "a b", "x" * 65, "..", "a*b"])
def test_normalize_char_id_rejects_invalid(bad):
    with pytest.raises(InvalidCharId):
        normalize_char_id(bad)


def test_validate_video_accepts_webm_magic():
    validate_video_bytes(b"\x1a\x45\xdf\xa3rest", filename="01.webm")


def test_validate_video_rejects_wrong_extension():
    with pytest.raises(InvalidUpload):
        validate_video_bytes(b"\x1a\x45\xdf\xa3", filename="01.mp4")


def test_validate_video_rejects_wrong_magic():
    with pytest.raises(InvalidUpload):
        validate_video_bytes(b"NOPEnotwebm", filename="01.webm")


def test_validate_data_accepts_gzip_magic():
    validate_data_bytes(b"\x1f\x8brest", filename="combined_data.json.gz")


def test_validate_data_rejects_wrong_extension():
    with pytest.raises(InvalidUpload):
        validate_data_bytes(b"\x1f\x8b", filename="data.json")


def test_validate_data_rejects_wrong_magic():
    with pytest.raises(InvalidUpload):
        validate_data_bytes(b"PK\x03\x04", filename="combined_data.json.gz")

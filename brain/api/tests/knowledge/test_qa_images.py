"""QR detection for QA images: readable QR codes only, classified once per file."""

from __future__ import annotations

from pathlib import Path

import pytest

import knowledge.qa_images as qa_images
from protocol.history import serialize_history_messages

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

QR_PNG = (Path(__file__).parent / "fixtures" / "qr_sample.png").read_bytes()
URL = "https://example.com/qa/1"


def _qr_image():
    return cv2.imdecode(np.frombuffer(QR_PNG, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)


def _encode(image, ext=".png") -> bytes:
    ok, data = cv2.imencode(ext, image)
    assert ok
    return data.tobytes()


def test_a_plain_qr_is_recognised_with_its_content():
    result = qa_images.classify_image(QR_PNG)
    assert result["kind"] == qa_images.KIND_QR
    assert result["qr_payload"] == URL


def test_transparent_background_is_flattened_before_reading():
    gray = _qr_image()
    # 黑色模組不透明、白底全透明：直接讀會整張變黑。
    bgra = np.dstack([np.zeros_like(gray)] * 3 + [255 - gray])
    assert qa_images.classify_image(_encode(bgra))["kind"] == qa_images.KIND_QR


def test_inverted_qr_is_recognised():
    assert qa_images.classify_image(_encode(255 - _qr_image()))["qr_payload"] == URL


def test_a_small_qr_on_a_poster_stays_an_image():
    poster = np.full((1600, 1200), 235, dtype=np.uint8)
    qr = cv2.resize(_qr_image(), (300, 300), interpolation=cv2.INTER_NEAREST)
    poster[1280:1580, 880:1180] = qr
    result = qa_images.classify_image(_encode(poster))
    assert result["qr_payload"] == URL  # 讀得到內容
    assert result["kind"] == qa_images.KIND_IMAGE


def test_an_ordinary_picture_is_an_image():
    gradient = np.tile(np.linspace(0, 255, 400, dtype=np.uint8), (300, 1))
    assert qa_images.classify_image(_encode(gradient, ".jpg"))["kind"] == qa_images.KIND_IMAGE


def test_undecodable_bytes_count_as_an_image():
    assert qa_images.classify_image(b"not an image")["kind"] == qa_images.KIND_IMAGE


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / "knowledge" / ".qa_images").mkdir(parents=True)
    monkeypatch.setattr(qa_images, "ensure_workspace_scaffold", lambda _project: tmp_path)
    return tmp_path / "knowledge" / ".qa_images"


def _count_classify(monkeypatch):
    calls = []
    real = qa_images.classify_image
    monkeypatch.setattr(
        qa_images, "classify_image", lambda data: calls.append(1) or real(data),
    )
    return calls


def test_each_file_is_classified_once(project, monkeypatch):
    (project / "a.png").write_bytes(QR_PNG)
    calls = _count_classify(monkeypatch)
    assert qa_images.qa_image_kind("a.png", "p") == qa_images.KIND_QR
    assert qa_images.qa_image_kind("a.png", "p") == qa_images.KIND_QR
    assert len(calls) == 1


def test_replacing_a_file_classifies_it_again(project, monkeypatch):
    target = project / "a.png"
    target.write_bytes(QR_PNG)
    assert qa_images.qa_image_kind("a.png", "p") == qa_images.KIND_QR
    plain = np.tile(np.linspace(0, 255, 400, dtype=np.uint8), (300, 1))
    target.write_bytes(_encode(plain))
    assert qa_images.qa_image_kind("a.png", "p") == qa_images.KIND_IMAGE


def test_ids_without_extension_or_spaces_resolve_like_the_image_route(project):
    (project / "PRP (1).png").write_bytes(QR_PNG)
    assert qa_images.qa_image_kind("PRP(1)", "p") == qa_images.KIND_QR


def test_missing_image_or_classifier_failure_is_unknown_not_an_error(project, monkeypatch):
    assert qa_images.qa_image_kind("nope.png", "p") is None
    assert qa_images.qa_image_kind("../escape.png", "p") is None
    (project / "a.png").write_bytes(QR_PNG)

    def boom(_data):
        raise RuntimeError("no cv2")

    monkeypatch.setattr(qa_images, "classify_image", boom)
    assert qa_images.qa_image_kind("a.png", "p") is None


def test_history_carries_the_kind():
    [entry] = serialize_history_messages([{
        "role": "assistant",
        "content": "x",
        "created_at": "2026-11-05T00:00:00+00:00",
        "metadata": {"image_id": "a.png", "image_kind": "qr"},
    }])
    assert entry["image_kind"] == "qr"

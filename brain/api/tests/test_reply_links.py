"""Project-level contact image and catalogue url carried by every reply."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from infra.project_context import resolve_project_context
from knowledge import qa_nodes
from knowledge.kb_settings import load_kb_settings, load_reply_links, save_kb_settings
from routes.knowledge import router

_QR = "0f1e2d3c-4b5a-4968-8776-655443322110.png"
_URL = "/brain/knowledge/reply-links"
_PROJECT = "reply-links"


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, headers={"X-Internal-Token": "test-internal-token"})


@pytest.fixture
def root():
    return resolve_project_context(_PROJECT).workspace_root


def _settings_file(root):
    return root / ".kb_settings.json"


def _qr_file(root, name=_QR):
    images = root / "knowledge" / ".qa_images"
    images.mkdir(parents=True, exist_ok=True)
    (images / name).write_bytes(b"\x89PNG\r\n\x1a\n")


def _put(client, image=None, url=None):
    return client.put(_URL, json={"project_id": _PROJECT, "contact_image_id": image, "catalog_url": url})


def test_nothing_set_reads_back_nulls(client):
    assert client.get(_URL, params={"project_id": _PROJECT}).json() == {
        "contact_image_id": None, "catalog_url": None,
    }


def test_set_read_back_and_clear(client, root):
    _qr_file(root)
    saved = _put(client, _QR, "https://example.com/catalog.pdf")
    assert saved.status_code == 200
    expected = {"contact_image_id": _QR, "catalog_url": "https://example.com/catalog.pdf"}
    assert saved.json() == expected
    assert client.get(_URL, params={"project_id": _PROJECT}).json() == expected
    assert load_reply_links(_PROJECT) == expected

    assert _put(client).status_code == 200
    assert load_reply_links(_PROJECT) == {"contact_image_id": None, "catalog_url": None}
    assert "contact_image_id" not in json.loads(_settings_file(root).read_text())


def test_other_settings_survive_and_do_not_leak_into_the_settings_api(client, root):
    _qr_file(root)
    save_kb_settings(_PROJECT, language_routes=["en"], reply_seconds=0)
    stored = json.loads(_settings_file(root).read_text())
    stored.update({"graph_enabled": True, "memory_enabled": False, "custom": 1})
    _settings_file(root).write_text(json.dumps(stored), encoding="utf-8")

    _put(client, _QR, "https://example.com/c")
    after = json.loads(_settings_file(root).read_text())
    assert after["language_routes"] == ["en"] and after["reply_seconds"] == 0
    assert after["graph_enabled"] is True and after["memory_enabled"] is False and after["custom"] == 1

    # 設定頁的回應不多出附件欄位；改語言分流也不會洗掉附件。
    assert "catalog_url" not in load_kb_settings(_PROJECT)
    save_kb_settings(_PROJECT, language_routes=["zh"])
    assert load_reply_links(_PROJECT)["catalog_url"] == "https://example.com/c"


@pytest.mark.parametrize("image", ["../SOUL.md", "qr.png", "0f1e2d3c-4b5a-4968-8776-655443322110.svg", ""])
def test_contact_image_only_accepts_uploaded_qa_image_ids(client, root, image):
    _qr_file(root)
    assert _put(client, image).status_code == 400
    assert load_reply_links(_PROJECT)["contact_image_id"] is None


def test_contact_image_file_must_exist(client):
    assert _put(client, _QR).status_code == 400


@pytest.mark.parametrize("url", [
    "http://example.com/a", "javascript:alert(1)", "ftp://example.com", "//example.com",
    "example.com", "https://", "", "   ", "https://example.com/a b",
    "https://example.com/" + "a" * 500,
])
def test_catalog_url_only_accepts_https_within_500_chars(client, url):
    assert _put(client, None, url).status_code == 400
    assert load_reply_links(_PROJECT)["catalog_url"] is None


def test_catalog_url_at_the_limit_is_accepted(client):
    url = "https://example.com/" + "a" * (500 - len("https://example.com/"))
    assert _put(client, None, url).status_code == 200


def test_a_rejected_write_changes_nothing(client, root):
    _qr_file(root)
    _put(client, _QR, "https://example.com/ok")
    assert _put(client, _QR, "http://bad").status_code == 400
    assert load_reply_links(_PROJECT) == {"contact_image_id": _QR, "catalog_url": "https://example.com/ok"}


def test_unreadable_settings_file_means_no_links(root):
    root.mkdir(parents=True, exist_ok=True)
    _settings_file(root).write_text("{broken", encoding="utf-8")
    assert load_reply_links(_PROJECT) == {"contact_image_id": None, "catalog_url": None}
    _settings_file(root).write_text(json.dumps({"contact_image_id": 5, "catalog_url": "http://x"}), encoding="utf-8")
    assert load_reply_links(_PROJECT) == {"contact_image_id": None, "catalog_url": None}


def test_image_cleanup_keeps_the_project_contact_image(client, root, monkeypatch):
    import os
    import time

    _qr_file(root)
    stray_name = "11111111-2222-4333-8444-555555555555.png"
    _qr_file(root, stray_name)
    _put(client, _QR)
    old = time.time() - 3600
    for path in (root / "knowledge" / ".qa_images").iterdir():
        os.utime(path, (old, old))
    monkeypatch.setattr(qa_nodes, "ensure_workspace_scaffold", lambda project_id="default": root)

    deleted = qa_nodes.cleanup_unused_images(_PROJECT)

    assert (root / "knowledge" / ".qa_images" / _QR).exists()
    assert not (root / "knowledge" / ".qa_images" / stray_name).exists()
    assert any(stray_name in item for item in deleted)


def test_a_hand_edited_broken_catalog_url_never_breaks_replies(root):
    root.mkdir(parents=True, exist_ok=True)
    _settings_file(root).write_text(json.dumps({"catalog_url": "https://[::1"}), encoding="utf-8")
    assert load_reply_links(_PROJECT) == {"contact_image_id": None, "catalog_url": None}
    _settings_file(root).write_text("[1, 2]", encoding="utf-8")
    assert load_reply_links(_PROJECT) == {"contact_image_id": None, "catalog_url": None}


def test_image_cleanup_keeps_a_contact_image_still_set_on_a_persona(root, monkeypatch):
    """舊版設在人設 AVATAR.json 的聯絡圖片，還沒改設成專案層級前不能被清掉。"""
    import os
    import time

    legacy = "22222222-3333-4444-8555-666666666666.png"
    _qr_file(root, legacy)
    persona_dir = root / "personas" / "kiosk"
    persona_dir.mkdir(parents=True, exist_ok=True)
    (persona_dir / "SOUL.md").write_text("# Kiosk\n", encoding="utf-8")
    (persona_dir / "AVATAR.json").write_text(json.dumps({"contact_image_id": legacy}), encoding="utf-8")
    old = time.time() - 3600
    for path in (root / "knowledge" / ".qa_images").iterdir():
        os.utime(path, (old, old))
    monkeypatch.setattr(qa_nodes, "ensure_workspace_scaffold", lambda project_id="default": root)

    qa_nodes.cleanup_unused_images(_PROJECT)

    assert (root / "knowledge" / ".qa_images" / legacy).exists()

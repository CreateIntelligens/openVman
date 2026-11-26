"""Per-language greetings and voices live next to the persona's avatar binding."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowledge import workspace
from personas import personas
from routes import personas as persona_routes

_TOKEN = {"X-Internal-Token": "test-internal-token"}
_URL = "/brain/personas/language-settings"


@pytest.fixture
def root(monkeypatch, tmp_path) -> Path:
    root = tmp_path / "workspace"
    (root / "personas").mkdir(parents=True)
    (root / "SOUL.md").write_text("# Global Soul", encoding="utf-8")
    monkeypatch.setattr(workspace, "get_workspace_root", lambda project_id="default": root)
    personas.create_persona_scaffold("guide", "Guide", "default")
    return root


@pytest.fixture
def client(root) -> TestClient:
    app = FastAPI()
    app.include_router(persona_routes.router)
    return TestClient(app, headers=_TOKEN)


def _put(client, persona_id="guide", greetings=None, voices=None):
    return client.put(_URL, json={
        "persona_id": persona_id, "project_id": "default",
        "greetings": {} if greetings is None else greetings,
        "voices": {} if voices is None else voices,
    })


def test_put_then_get_reads_back_trimmed_text(client):
    put = _put(client, greetings={"en": "  Hello!  ", "zh": "你好"}, voices={"en": "en_US-amy:v1.2"})
    assert put.status_code == 200
    expected = {
        "persona_id": "guide",
        "greetings": {"en": "Hello!", "zh": "你好"},
        "voices": {"en": "en_US-amy:v1.2"},
    }
    assert put.json() == expected
    assert client.get(_URL, params={"persona_id": "guide"}).json() == expected


def test_put_replaces_the_whole_settings_and_keeps_other_meta_fields(client, root):
    personas.set_persona_avatar("guide", "008", "default")
    _put(client, greetings={"en": "Hello", "es": "Hola"}, voices={"en": "a", "es": "b"})
    _put(client, greetings={"es": "Hola de nuevo"})

    assert client.get(_URL, params={"persona_id": "guide"}).json() == {
        "persona_id": "guide", "greetings": {"es": "Hola de nuevo"}, "voices": {},
    }
    meta = json.loads((root / "personas" / "guide" / "AVATAR.json").read_text(encoding="utf-8"))
    assert meta["avatar_char_id"] == "008"
    # 反過來：綁定頭像不會洗掉語言設定。
    _put(client, greetings={"en": "Hello"})
    personas.set_persona_avatar("guide", "009", "default")
    assert client.get(_URL, params={"persona_id": "guide"}).json()["greetings"] == {"en": "Hello"}


def test_an_old_meta_file_without_the_fields_reads_as_empty(client, root):
    (root / "personas" / "guide" / "AVATAR.json").write_text('{"avatar_char_id": "001"}', encoding="utf-8")
    assert client.get(_URL, params={"persona_id": "guide"}).json() == {
        "persona_id": "guide", "greetings": {}, "voices": {},
    }


def test_the_default_persona_can_be_set(client, root):
    assert _put(client, "default", greetings={"ja": "こんにちは"}, voices={"ja": "ja-1"}).status_code == 200
    assert (root / "AVATAR.json").is_file()
    assert client.get(_URL).json() == {
        "persona_id": "default", "greetings": {"ja": "こんにちは"}, "voices": {"ja": "ja-1"},
    }


@pytest.mark.parametrize(
    ("greetings", "voices"),
    [
        ({"fr": "Bonjour"}, {}),
        ({"nan": "你好"}, {}),
        ({"en": "x" * 501}, {}),
        ({"en": "   "}, {}),
        ({"en": 3}, {}),
        ("Hello", {}),
        ({}, {"fr": "v"}),
        ({}, {"en": ""}),
        ({}, {"en": "a" * 129}),
        ({}, {"en": "bad voice"}),
        ({}, {"en": "../etc/passwd"}),
        ({}, {"en": 5}),
    ],
)
def test_invalid_settings_are_rejected_with_a_plain_message_and_nothing_is_saved(
    client, root, greetings, voices,
):
    _put(client, greetings={"en": "Keep me"})
    response = _put(client, greetings=greetings, voices=voices)

    assert response.status_code == 400
    assert any("一" <= ch <= "鿿" for ch in response.json()["detail"])
    assert client.get(_URL, params={"persona_id": "guide"}).json()["greetings"] == {"en": "Keep me"}


def test_a_500_character_greeting_and_a_128_character_voice_are_the_limits(client):
    response = _put(client, greetings={"en": "x" * 500}, voices={"en": "v" * 128})
    assert response.status_code == 200


def test_unknown_persona_is_404_and_a_bad_persona_id_is_400(client):
    assert _put(client, "ghost").status_code == 404
    assert client.get(_URL, params={"persona_id": "ghost"}).status_code == 404
    assert _put(client, "../x").status_code == 400
    assert client.get(
        "/brain/personas/greeting", params={"persona_id": "ghost", "language": "en"},
    ).status_code == 404


def test_greeting_returns_text_and_voice_or_404(client):
    _put(client, greetings={"en": "Hello", "es": "Hola"}, voices={"en": "en-voice"})
    url = "/brain/personas/greeting"

    assert client.get(url, params={"persona_id": "guide", "language": "en"}).json() == {
        "language": "en", "text": "Hello", "voice": "en-voice",
    }
    assert client.get(url, params={"persona_id": "guide", "language": "es"}).json() == {
        "language": "es", "text": "Hola", "voice": None,
    }
    assert client.get(url, params={"persona_id": "guide", "language": "ja"}).status_code == 404
    assert client.get(url, params={"persona_id": "guide", "language": "nan"}).status_code == 404
    assert client.get(url, params={"persona_id": "guide"}).status_code == 422


def test_requests_without_the_internal_token_are_refused(root):
    app = FastAPI()
    app.include_router(persona_routes.router)
    anonymous = TestClient(app)
    body = {"persona_id": "guide", "project_id": "default", "greetings": {"en": "x"}, "voices": {}}

    assert anonymous.put(_URL, json=body).status_code in {401, 403}
    assert anonymous.get(_URL).status_code in {401, 403}
    assert anonymous.get("/brain/personas/greeting", params={"language": "en"}).status_code in {401, 403}
    assert personas.get_persona_language_settings("guide")["greetings"] == {}


def test_greeting_uses_the_project_the_backend_resolved(root, client, monkeypatch):
    # 嵌入金鑰的請求網址沒帶專案時，Backend 把金鑰綁的專案放在標頭；不能退回 default。
    seen = []
    monkeypatch.setattr(persona_routes, "get_persona_greeting", lambda pid, lang, project: seen.append(project) or {"language": lang, "text": "hi", "voice": None})
    header = {"X-OpenVMan-Project-ID": "proj-bound"}

    assert client.get("/brain/personas/greeting", params={"language": "en"}, headers=header).status_code == 200
    assert client.get("/brain/personas/greeting", params={"language": "en", "project_id": "proj-bound"}, headers=header).status_code == 200
    assert client.get("/brain/personas/greeting", params={"language": "en", "project_id": "proj-other"}, headers=header).status_code == 400
    assert client.get("/brain/personas/greeting", params={"language": "en", "project_id": "proj-direct"}).status_code == 200
    assert seen == ["proj-bound", "proj-bound", "proj-direct"]


_LABEL = "/brain/personas/label"


def _rename(client, persona_id, label):
    return client.put(_LABEL, json={"persona_id": persona_id, "label": label})


def test_default_persona_shows_the_built_in_name_until_renamed(root, client):
    assert personas.list_personas()[0]["label"] == "預設角色"
    assert personas.default_persona_label("default") == "預設角色"


def test_renaming_the_default_persona_writes_root_avatar_json_and_keeps_other_fields(root, client):
    meta_path = root / "AVATAR.json"
    meta_path.write_text(json.dumps({"avatar_char_id": "008", "greetings": {"en": "Hello"}}), encoding="utf-8")

    response = _rename(client, "default", "  Mr. Walter  ")

    assert response.status_code == 200
    assert response.json() == {"persona_id": "default", "label": "Mr. Walter"}
    assert personas.list_personas()[0]["label"] == "Mr. Walter"
    assert json.loads(meta_path.read_text(encoding="utf-8")) == {
        "avatar_char_id": "008", "greetings": {"en": "Hello"}, "label": "Mr. Walter",
    }
    # 語言設定與虛擬人綁定不被洗掉，SOUL.md 也沒動。
    assert personas.get_persona_language_settings("default")["greetings"] == {"en": "Hello"}
    assert (root / "SOUL.md").read_text(encoding="utf-8") == "# Global Soul"


def test_renaming_another_persona_writes_its_avatar_json_and_leaves_soul_alone(root, client):
    soul = root / "personas" / "guide" / "SOUL.md"
    soul.write_text("# Old Name\n\n## 角色設定\n\n你是導覽員。\n", encoding="utf-8")
    personas.set_persona_avatar("guide", "char-1", "default")

    assert _rename(client, "guide", "新導覽員").status_code == 200

    # SOUL.md 是給模型的提示詞，改顯示名稱不碰它。
    assert soul.read_text(encoding="utf-8") == "# Old Name\n\n## 角色設定\n\n你是導覽員。\n"
    meta = json.loads((root / "personas" / "guide" / "AVATAR.json").read_text(encoding="utf-8"))
    assert meta == {"avatar_char_id": "char-1", "label": "新導覽員"}
    listed = {item["persona_id"]: item for item in personas.list_personas()}
    assert listed["guide"]["label"] == "新導覽員"
    assert listed["guide"]["avatar_char_id"] == "char-1"


def test_unnamed_persona_still_shows_its_soul_title(root):
    soul = root / "personas" / "guide" / "SOUL.md"
    soul.write_text("# 導覽員\n\n你是導覽員。\n", encoding="utf-8")
    assert {item["persona_id"]: item["label"] for item in personas.list_personas()}["guide"] == "導覽員"


@pytest.mark.parametrize("label", ["", "   ", "x" * 41, "兩\n行"])
def test_label_must_be_one_to_forty_characters_on_one_line(root, client, label):
    assert _rename(client, "default", label).status_code == 400
    assert _rename(client, "guide", label).status_code == 400
    assert personas.list_personas()[0]["label"] == "預設角色"


def test_label_at_forty_characters_is_accepted_and_unknown_persona_is_404(root, client):
    assert _rename(client, "default", "字" * 40).status_code == 200
    assert _rename(client, "nobody", "名稱").status_code == 404


def test_unreadable_default_label_falls_back(root):
    (root / "AVATAR.json").write_text(json.dumps({"label": ["x"]}), encoding="utf-8")
    assert personas.default_persona_label("default") == "預設角色"
    (root / "AVATAR.json").write_text(json.dumps({"label": "字" * 41}), encoding="utf-8")
    assert personas.default_persona_label("default") == "預設角色"


@pytest.mark.parametrize("path", ["/brain/personas/contact-image", "/brain/personas/reference-link"])
def test_persona_level_reply_attachment_routes_are_gone(client, path):
    assert client.put(path, json={"persona_id": "guide", "image_id": None, "url": None}).status_code in {404, 405}

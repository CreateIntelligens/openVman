import json
from unittest.mock import patch

import pytest

from core import chat_service


def _ctx(**over):
    base = dict(
        trace_id="t", persona_id="default", project_id="default",
        session_id="s-eph", route=None, user_message="[視覺事件] 出現訪客",
        request_context={"metadata": {"ephemeral_user_message": True}},
        prompt_messages=[], prior_messages=[],
    )
    base.update(over)
    return chat_service.GenerationContext(**base)


@pytest.mark.usefixtures("default_project_memory")
def test_ephemeral_skips_user_message_but_persists_reply():
    appended = []

    def fake_append(session_id, persona_id, role, content, **kw):
        appended.append(role)
        return (None, f"id-{role}")

    with (
        patch.object(chat_service, "append_session_message_with_id", side_effect=fake_append),
        patch.object(chat_service, "archive_session_turn") as mock_archive,
        patch.object(chat_service, "_schedule_memory_writes"),
        patch.object(chat_service, "_serialize_history_message", lambda m: m),
    ):
        chat_service.finalize_generation(_ctx(), "你好，歡迎光臨！")

    assert "user" not in appended
    assert "assistant" in appended
    # 視覺脈絡不得寫入 daily archive（避免後續向量化落入記憶）
    mock_archive.assert_not_called()


@pytest.mark.usefixtures("default_project_memory")
def test_non_ephemeral_persists_both():
    appended = []

    def fake_append(session_id, persona_id, role, content, **kw):
        appended.append(role)
        return (None, f"id-{role}")

    with (
        patch.object(chat_service, "append_session_message_with_id", side_effect=fake_append),
        patch.object(chat_service, "archive_session_turn") as mock_archive,
        patch.object(chat_service, "_schedule_memory_writes"),
        patch.object(chat_service, "_serialize_history_message", lambda m: m),
    ):
        chat_service.finalize_generation(
            _ctx(request_context={"metadata": {}}), "一般回覆",
        )

    assert "user" in appended and "assistant" in appended
    mock_archive.assert_called_once()


def test_finalize_returns_and_persists_primary_citation_media():
    assistant_metadata = {}

    def fake_append(session_id, persona_id, role, content, **kwargs):
        if role == "assistant":
            assistant_metadata.update(kwargs.get("metadata") or {})
        return (None, f"id-{role}")

    tool_steps = [
        {
            "name": "search_knowledge",
            "result": json.dumps(
                {
                    "status": "ok",
                    "data": {
                        "citations": [
                            {
                                "uri": "knowledge/qa/line.csv",
                                "title": "官方 LINE",
                                "text": "請掃描 QR code",
                                "distance": 0.1,
                                "image_id": "B1-4",
                                "url": "https://example.com/line",
                            }
                        ]
                    },
                }
            ),
        }
    ]

    with (
        patch.object(
            chat_service,
            "append_session_message_with_id",
            side_effect=fake_append,
        ),
        patch.object(chat_service, "archive_session_turn"),
        patch.object(chat_service, "_schedule_memory_writes"),
    ):
        response = chat_service.finalize_generation(
            _ctx(),
            "請掃描院內提供的 QR code。",
            tool_steps,
        )

    assert response["image_id"] == "B1-4"
    assert response["url"] == "https://example.com/line"
    assert response["citations"][0]["image_id"] == "B1-4"
    assert response["history"][-1]["image_id"] == "B1-4"
    assert assistant_metadata["image_id"] == "B1-4"
    assert assistant_metadata["url"] == "https://example.com/line"


def test_finalize_adds_the_persona_contact_image_next_to_the_cited_picture():
    tool_steps = [{
        "name": "search_knowledge",
        "result": json.dumps({"status": "ok", "data": {"citations": [{
            "uri": "knowledge/qa/catalog.csv", "title": "EG", "text": "刀組 AISI 440C",
            "distance": 0.1, "image_id": "eg.webp",
        }]}}),
    }]
    kinds = {"eg.webp": "image", "qr.png": "qr"}
    with (
        patch.object(chat_service, "append_session_message_with_id", return_value=(None, "id")),
        patch.object(chat_service, "archive_session_turn"),
        patch.object(chat_service, "_schedule_memory_writes"),
        patch.object(chat_service, "persona_contact_image", return_value="qr.png"),
        patch.object(chat_service, "qa_image_kind", side_effect=lambda image_id, _p: kinds.get(image_id)),
    ):
        response = chat_service.finalize_generation(_ctx(), "刀組是 AISI 440C。", tool_steps)

    # 產品圖照舊放 image_id，QR 放另一個欄位，兩張都在。
    assert (response["image_id"], response["image_kind"]) == ("eg.webp", "image")
    assert (response["contact_image_id"], response["contact_image_kind"]) == ("qr.png", "qr")


def test_finalize_without_a_contact_image_adds_no_field():
    with (
        patch.object(chat_service, "append_session_message_with_id", return_value=(None, "id")),
        patch.object(chat_service, "archive_session_turn"),
        patch.object(chat_service, "_schedule_memory_writes"),
        patch.object(chat_service, "persona_contact_image", return_value=None),
    ):
        response = chat_service.finalize_generation(_ctx(), "你好。", [])

    assert "contact_image_id" not in response

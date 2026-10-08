"""Cancelled HTTP replies must not enter history or automatic memory."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import chat_service
from core.pipeline import RouteDecision
from memory import memory
from memory.session_store import SessionStore
from routes import chat as chat_routes
from safety.internal_auth import require_internal_token


@pytest.fixture
def delivery(tmp_path, monkeypatch):
    store = SessionStore(str(tmp_path / "sessions.db"))
    monkeypatch.setattr(memory, "get_session_store", lambda _: store)
    monkeypatch.setattr(memory, "_primary_language", lambda _: "zh")
    monkeypatch.setattr(
        "memory.session_store.refine_language_in_background",
        lambda *args: None,
    )
    archive = Mock()
    governance = Mock()
    monkeypatch.setattr(chat_service, "archive_session_turn", archive)
    monkeypatch.setattr(chat_service, "_schedule_memory_writes", governance)
    monkeypatch.setattr(chat_service, "_scan_reply_pii", lambda *args: None)
    monkeypatch.setattr(chat_service, "_patch_reply_pii_metadata", lambda *args: None)

    def prepare(request, payload):
        store.get_or_create_session(payload.session_id, payload.persona_id)
        return chat_service.GenerationContext(
            trace_id="trace", persona_id=payload.persona_id,
            project_id=payload.project_id, session_id=payload.session_id,
            route=RouteDecision("direct", True, True),
            user_message=payload.message, prompt_messages=[],
            request_context={"metadata": payload.metadata},
            prior_messages=store.list_messages(payload.session_id),
        )

    monkeypatch.setattr(chat_routes, "_prepare_chat_context", prepare)
    monkeypatch.setattr(
        chat_routes, "execute_generation",
        lambda context: SimpleNamespace(
            reply=f"回答：{context.user_message}", tool_steps=[],
        ),
    )
    app = FastAPI()
    app.dependency_overrides[require_internal_token] = lambda: None
    app.include_router(chat_routes.router)
    with TestClient(app, headers={"X-Principal-Id": "user-1"}) as client:
        yield client, store, archive, governance


def turn(revision=1, **overrides):
    return {
        "project_id": "default", "persona_id": "default",
        "session_id": "s1", "turn_id": "turn-1",
        "turn_revision": revision, **overrides,
    }


def generate(client, revision=1, message="沉水泵多深？"):
    return client.post("/brain/chat", json={**turn(revision), "message": message})


def test_unreceived_answer_has_no_history_archive_or_memory(delivery):
    client, store, archive, governance = delivery
    response = generate(client)
    assert response.status_code == 200
    assert response.json()["requires_accept"] is True
    assert store.list_messages("s1") == []
    archive.assert_not_called()
    governance.assert_not_called()


def test_generated_but_unreceived_reply_can_be_replaced(delivery):
    client, store, archive, governance = delivery
    assert generate(client).status_code == 200
    merged = "沉水泵多深？\n還有馬力多大？"
    assert generate(client, 2, merged).status_code == 200
    assert client.post("/brain/chat/accept", json=turn()).status_code == 409
    assert store.list_messages("s1") == []
    accepted = client.post("/brain/chat/accept", json=turn(2))
    assert accepted.status_code == 200
    assert accepted.json()["requires_accept"] is False
    assert [m["content"] for m in store.list_messages("s1")] == [
        merged, f"回答：{merged}",
    ]
    archive.assert_called_once()
    governance.assert_called_once()
    # Retries may acknowledge again after the first HTTP response was lost.
    assert client.post("/brain/chat/accept", json=turn(2)).status_code == 200
    assert len(store.list_messages("s1")) == 2
    archive.assert_called_once()
    governance.assert_called_once()


def test_late_first_generation_cannot_overwrite_the_merged_reply(
    delivery, monkeypatch,
):
    client, store, archive, governance = delivery
    started, release = Event(), Event()

    def generate_reply(context):
        if context.user_message == "第一句":
            started.set()
            assert release.wait(10)
        return SimpleNamespace(reply=context.user_message, tool_steps=[])

    monkeypatch.setattr(chat_routes, "execute_generation", generate_reply)
    with ThreadPoolExecutor() as pool:
        first = pool.submit(generate, client, 1, "第一句")
        try:
            assert started.wait(10)
            assert generate(client, 2, "第一句\n第二句").status_code == 200
        finally:
            release.set()
        assert first.result(timeout=10).status_code == 409
    assert client.post("/brain/chat/accept", json=turn(2)).status_code == 200
    assert len(store.list_messages("s1")) == 2
    archive.assert_called_once()
    governance.assert_called_once()


def test_reordered_revision_and_accepted_turn_cannot_be_replaced(delivery):
    client, store, _, _ = delivery
    assert generate(client, 2).status_code == 200
    assert generate(client, 1).status_code == 409
    assert client.post("/brain/chat/accept", json=turn(2)).status_code == 200
    assert generate(client, 3).status_code == 409
    assert len(store.list_messages("s1")) == 2


def test_acknowledgement_is_scoped_to_principal_and_persona(delivery):
    client, store, _, _ = delivery
    assert generate(client).status_code == 200
    stolen = client.post(
        "/brain/chat/accept", json=turn(),
        headers={"X-Principal-Id": "user-2"},
    )
    assert stolen.status_code == 409
    assert client.post(
        "/brain/chat/accept", json=turn(persona_id="other"),
    ).status_code == 409
    assert store.list_messages("s1") == []
    assert client.post("/brain/chat/accept", json=turn()).status_code == 200
    assert len(store.list_messages("s1")) == 2


def test_accepted_turn_reuses_server_resolved_input_language(delivery):
    _, store, _, _ = delivery
    assert store.register_chat_turn("s1", "default", "user:user-1", "turn-language", 1)
    payload = {
        "context": {
            "persona_id": "default",
            "user_message": "What did we decide?",
            "request_context": {"metadata": {}},
            "input_language": "en",
        },
        "response": {
            "reply": "We decided to continue.",
            "history": [{"role": "assistant", "content": "We decided to continue."}],
        },
        "tool_steps": [],
        "response_time_s": 0.2,
    }
    assert store.stage_chat_turn("s1", "user:user-1", "turn-language", 1, payload)

    accepted = store.accept_chat_turn(
        "s1", "default", "user:user-1", "turn-language", 1,
    )

    assert accepted is not None
    with store._connect() as conn:
        row = conn.execute(
            "SELECT language FROM messages WHERE session_id = ? AND role = 'user'",
            ("s1",),
        ).fetchone()
    assert row == ("en",)


def test_sqlite_guards_work_between_independent_store_instances(delivery):
    client, store, _, _ = delivery
    assert generate(client).status_code == 200
    other_worker = SessionStore(str(store._db_path))
    assert other_worker.register_chat_turn(
        "s1", "default", "user:user-1", "turn-1", 2,
    )
    assert store.accept_chat_turn(
        "s1", "default", "user:user-1", "turn-1", 1,
    ) is None
    assert store.list_messages("s1") == []


@pytest.mark.parametrize("invalid", [
    {"turn_revision": None}, {"turn_id": None},
    {"session_id": None}, {"turn_revision": "1"},
    {"turn_revision": 0}, {"metadata": {"ephemeral_user_message": True}},
])
def test_incomplete_or_invalid_turn_contract_is_rejected(delivery, invalid):
    client, _, _, _ = delivery
    response = client.post(
        "/brain/chat", json={**turn(), "message": "你好", **invalid},
    )
    assert response.status_code == 422

"""Public contracts describe the credential actually accepted by middleware."""

from copy import deepcopy

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.brain_proxy import router as brain_router
from app.openapi import _merge_brain_openapi, _with_account_authentication


def test_auth_contract_distinguishes_session_management_and_embed_routes():
    schema = {"paths": {
        "/api/v1/auth/login": {"post": {}},
        "/api/v1/asr/transcribe": {"post": {}},
        "/api/v1/chat": {"post": {}},
        "/api/v1/api-keys": {"get": {}, "post": {}},
        "/api/v1/api-keys/{key_id}": {"delete": {}},
        "/api/v1/internal/enrich": {"post": {
            "security": [{"InternalToken": []}],
        }},
    }}
    original = deepcopy(schema)
    result = _with_account_authentication(schema)
    assert schema == original
    paths = result["paths"]
    assert "security" not in paths["/api/v1/auth/login"]["post"]
    assert paths["/api/v1/asr/transcribe"]["post"]["security"] == [
        {"AccountBearer": []}, {"AccountCookie": []},
    ]
    assert paths["/api/v1/chat"]["post"]["security"][-1] == {"EmbedKey": []}
    assert paths["/api/v1/api-keys"]["post"]["security"][0] == {
        "SessionBearer": [],
    }
    assert paths["/api/v1/api-keys/{key_id}"]["delete"]["security"][0] == {
        "SessionBearer": [],
    }
    assert paths["/api/v1/internal/enrich"]["post"]["security"] == [
        {"InternalToken": []},
    ]
    assert set(paths["/api/v1/asr/transcribe"]["post"]["responses"]) == {
        "401", "403", "429",
    }
    assert "429" in paths["/api/v1/chat"]["post"]["responses"]
    # 管理 API key 只收登入 token、登入路由免驗證，都不經 API key 限流。
    assert "429" not in paths["/api/v1/api-keys"]["post"]["responses"]
    assert "responses" not in paths["/api/v1/auth/login"]["post"]
    schemes = result["components"]["securitySchemes"]
    assert schemes["AccountBearer"]["scheme"] == "bearer"
    assert schemes["AccountCookie"]["name"] == "openvman_session"
    assert schemes["EmbedKey"]["name"] == "X-Embed-Key"


def test_auth_annotation_preserves_domain_responses():
    operation = {"responses": {"403": {"description": "Project denied"}}}
    result = _with_account_authentication({
        "paths": {"/api/v1/projects": {"get": operation}},
    })
    assert result["paths"]["/api/v1/projects"]["get"]["responses"]["403"] == {
        "description": "Project denied",
    }


def _brain_proxy_schema() -> dict:
    app = FastAPI()
    app.include_router(brain_router)
    return get_openapi(title="t", version="1", routes=app.routes)


def test_chat_stream_documents_event_stream_only():
    responses = _brain_proxy_schema()["paths"]["/api/v1/chat/stream"]["post"][
        "responses"
    ]
    assert set(responses["200"]["content"]) == {"text/event-stream"}
    assert "sentence" in responses["200"]["description"]


def test_project_scoped_proxy_routes_document_project_errors():
    paths = _brain_proxy_schema()["paths"]
    for path, method in (
        ("/api/v1/chat", "post"),
        ("/api/v1/chat/stream", "post"),
        ("/api/v1/knowledge/documents", "get"),
        ("/api/v1/memories", "post"),
    ):
        responses = paths[path][method]["responses"]
        assert "404" in responses, path
        assert "project_id" in responses["422"]["description"], path
    assert "404" not in paths["/api/v1/health"]["get"]["responses"]
    assert "422" not in paths["/api/v1/health"]["get"]["responses"]
    assert "404" not in paths["/api/v1/projects"]["get"]["responses"]


def test_brain_merge_keeps_brain_responses_and_backend_overrides():
    local = {"paths": {"/api/v1/chat/stream": {"post": {
        "summary": "Backend",
        "responses": {
            "200": {"content": {"text/event-stream": {}}},
            "404": {"description": "project"},
        },
    }}}}
    brain = {"paths": {"/brain/chat/stream": {"post": {
        "summary": "Brain",
        "requestBody": {"$ref": "ChatRequest"},
        "responses": {
            "200": {"content": {"application/json": {}}},
            "422": {"description": "Validation Error"},
        },
    }}}}
    operation = _merge_brain_openapi(local, brain)["paths"][
        "/api/v1/chat/stream"
    ]["post"]
    assert operation["summary"] == "Backend"
    assert operation["requestBody"] == {"$ref": "ChatRequest"}
    assert set(operation["responses"]) == {"200", "404", "422"}
    assert set(operation["responses"]["200"]["content"]) == {"text/event-stream"}

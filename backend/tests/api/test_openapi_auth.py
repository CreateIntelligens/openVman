"""Public contracts describe the credential actually accepted by middleware."""

from copy import deepcopy

from app.openapi import _with_account_authentication


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
        "401", "403",
    }
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

"""ROOT scope marking and policy exemption tests across resources, APIs and cache."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
import pytest

from app import project_routes
from app.auth.dependencies import AuthTransport, CurrentAccount
from app.auth.middleware import FailClosedAuthMiddleware
from app.auth.models import (
    AccountRole,
    ResourceType,
    ResourceVisibility,
)
from app.auth.project_resources import (
    effective_project_default,
    effective_project_resources,
)
from app.auth.runtime import get_auth_runtime
from app.auth.voice_access import (
    embed_tts_providers,
    project_voice_for_providers,
    resolve_tts_voice,
    scoped_tts_providers,
    tts_fallback_voice,
)
from app.config import get_tts_config
from app.gateway.asr_stream import _engine_for as asr_stream_engine_for
from app.routes import admin, avatar, backgrounds, capabilities, mascots, tts
from app.tts_cache import make_cache_key
from app.voice_policy import (
    batch_asr_scope,
    effective_asr_engine,
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AVATAR_ASSETS_DIR", str(tmp_path / "avatar"))
    monkeypatch.setenv("AVATAR_BACKGROUNDS_DIR", str(tmp_path / "backgrounds"))
    monkeypatch.setenv("AVATAR_MASCOTS_DIR", str(tmp_path / "mascots"))
    monkeypatch.setenv("ASR_PROVIDER", "breeze")
    monkeypatch.setenv("ASR_BREEZE_URL", "https://private-breeze.example")
    monkeypatch.setenv("ASR_R2T2_URL", "https://private-r2t2.example")

    get_tts_config.cache_clear()
    avatar.reset_store()
    backgrounds.reset_store()
    mascots.reset_store()

    runtime = get_auth_runtime()
    root = runtime.users.create_root(username="ai360", password_hash="unused")

    # 建立專案
    runtime.resources.upsert_system_resource(
        resource_type=ResourceType.PROJECT,
        resource_id="proj-1",
        metadata={"name": "Project One"},
    )

    # 建立角色、背景、小助理、聲音、ASR 資源
    resources = [
        (ResourceType.AVATAR_CHARACTER, "char-a", {"label": "Char A"}),
        (ResourceType.AVATAR_CHARACTER, "char-b", {"label": "Char B"}),
        (ResourceType.AVATAR_BACKGROUND, "bg-a", {"label": "Bg A"}),
        (ResourceType.AVATAR_BACKGROUND, "bg-b", {"label": "Bg B"}),
        (ResourceType.AVATAR_MASCOT, "mascot-a", {"label": "Mascot A"}),
        (ResourceType.AVATAR_MASCOT, "mascot-b", {"label": "Mascot B"}),
        (ResourceType.CUSTOM_VOICE, "voice-a", {"provider": "indextts"}),
        (ResourceType.CUSTOM_VOICE, "voice-b", {"provider": "cosyvoice"}),
        (ResourceType.CUSTOM_VOICE, "edge-v", {"provider": "edge-tts"}),
        (ResourceType.ASR_ENGINE, "r2t2", {"label": "R2T2"}),
        (ResourceType.ASR_ENGINE, "breeze", {"label": "Breeze"}),
        (ResourceType.ASR_ENGINE, "browser", {"label": "Browser"}),
    ]
    for r_type, r_id, meta in resources:
        runtime.resources.upsert_system_resource(
            resource_type=r_type, resource_id=r_id, metadata=meta,
        )

    # 一般成員與管理員
    member = runtime.users.create(
        username="member",
        password_hash="unused",
        role=AccountRole.USER,
        created_by=root.id,
        grants=[
            (ResourceType.PROJECT, "proj-1"),
            (ResourceType.AVATAR_CHARACTER, "char-a"),
            (ResourceType.AVATAR_CHARACTER, "char-b"),
            (ResourceType.AVATAR_BACKGROUND, "bg-a"),
            (ResourceType.AVATAR_BACKGROUND, "bg-b"),
            (ResourceType.AVATAR_MASCOT, "mascot-a"),
            (ResourceType.AVATAR_MASCOT, "mascot-b"),
            (ResourceType.CUSTOM_VOICE, "voice-a"),
            (ResourceType.CUSTOM_VOICE, "voice-b"),
            (ResourceType.ASR_ENGINE, "r2t2"),
            (ResourceType.ASR_ENGINE, "breeze"),
            (ResourceType.ASR_ENGINE, "browser"),
        ],
        defaults=("proj-1", "char-a", "indextts", "voice-a"),
    )
    admin_user = runtime.users.create(
        username="admin-user",
        password_hash="unused",
        role=AccountRole.ADMIN,
        created_by=root.id,
    )
    runtime.admin_scopes.replace(
        admin_user_id=admin_user.id,
        updated_by=root.id,
        scoped=True,
        resources=[
            (ResourceType.PROJECT, "proj-1"),
            (ResourceType.AVATAR_CHARACTER, "char-a"),
            (ResourceType.AVATAR_CHARACTER, "char-b"),
            (ResourceType.AVATAR_BACKGROUND, "bg-a"),
            (ResourceType.AVATAR_BACKGROUND, "bg-b"),
            (ResourceType.AVATAR_MASCOT, "mascot-a"),
            (ResourceType.AVATAR_MASCOT, "mascot-b"),
            (ResourceType.CUSTOM_VOICE, "voice-a"),
            (ResourceType.CUSTOM_VOICE, "voice-b"),
            (ResourceType.ASR_ENGINE, "r2t2"),
            (ResourceType.ASR_ENGINE, "breeze"),
            (ResourceType.ASR_ENGINE, "browser"),
        ],
    )

    # 建立專案政策：只允許 a 結尾的資源
    policy = runtime.project_policies.replace(
        project_id="proj-1",
        allowed_tts_voices=["voice-a"],
        default_tts_voice="voice-a",
        allowed_asr_engines=["r2t2"],
        default_asr_engine="r2t2",
        taiwanese_asr_engine="r2t2",
        allowed_characters=["char-a"],
        default_character_id="char-a",
        allowed_backgrounds=["bg-a"],
        default_background_id="bg-a",
        allowed_mascots=["mascot-a"],
        default_mascot_id="mascot-a",
        updated_by=root.id,
    )

    # 模擬前台所需之 store 項目
    monkeypatch.setattr(
        avatar.get_store(),
        "list_characters",
        lambda: [
            {"char_id": "char-a", "label": "Char A"},
            {"char_id": "char-b", "label": "Char B"},
        ],
    )
    monkeypatch.setattr(
        mascots,
        "get_character_store",
        avatar.get_store,
    )
    monkeypatch.setattr(
        mascots.get_store(),
        "list_mascots",
        lambda: [
            {"mascot_id": "mascot-a", "engine": "vrm"},
            {"mascot_id": "mascot-b", "engine": "vrm"},
        ],
    )
    monkeypatch.setattr(
        backgrounds.get_store(),
        "list_backgrounds",
        lambda: [
            {"background_id": "bg-a", "label": "Bg A"},
            {"background_id": "bg-b", "label": "Bg B"},
        ],
    )
    monkeypatch.setattr(
        project_routes,
        "proxy_to_brain",
        AsyncMock(return_value=JSONResponse({"projects": [
            {"project_id": "proj-1", "label": "Project One"},
        ]})),
    )

    app = FastAPI()
    app.include_router(project_routes.router)
    app.include_router(avatar.router)
    app.include_router(backgrounds.router)
    app.include_router(mascots.router)
    app.include_router(capabilities.router)
    app.include_router(tts.router)
    app.include_router(admin.router)
    app.add_middleware(FailClosedAuthMiddleware, runtime=runtime)
    app.dependency_overrides[get_auth_runtime] = lambda: runtime

    # Embed key
    embed_key = runtime.embed_keys.create(
        label="test-key",
        project_id="proj-1",
        allowed_origins=["http://localhost"],
        default_character_id="char-a",
        default_tts_provider="indextts",
        default_tts_voice="voice-a",
        created_by=root.id,
    )

    with TestClient(app, raise_server_exceptions=True) as client:
        yield SimpleNamespace(
            runtime=runtime,
            root=root,
            member=member,
            admin=admin_user,
            policy=policy,
            embed_key=embed_key,
            client=client,
            tmp_path=tmp_path,
        )


def _headers(env, user):
    return {"Authorization": f"Bearer {env.runtime.tokens.issue(user)}"}


def _current(user, embed_key=None):
    return CurrentAccount(
        user=user,
        transport=AuthTransport.BEARER if embed_key is None else AuthTransport.EMBED_KEY,
        embed_key=embed_key,
    )


def test_root_exempt_from_tts_voice_policy(env):
    """ROOT 可指定專案範圍外的聲音，admin 與 member 則被 403 拒絕；預設仍遵守專案預設。"""
    root_acc = _current(env.root)
    member_acc = _current(env.member)
    admin_acc = _current(env.admin)

    # 1. ROOT 指定不在專案清單的 voice-b: 成功解析 (200 語意)
    auth_root = resolve_tts_voice(
        root_acc, env.runtime,
        requested_provider="cosyvoice",
        requested_voice="voice-b",
        project_id="proj-1",
    )
    assert auth_root is not None
    assert auth_root.resource_id == "voice-b"

    # 2. Member 指定不在專案清單的 voice-b: 403
    with pytest.raises(HTTPException) as exc_member:
        resolve_tts_voice(
            member_acc, env.runtime,
            requested_provider="cosyvoice",
            requested_voice="voice-b",
            project_id="proj-1",
        )
    assert exc_member.value.status_code == 403

    # 3. Admin 指定不在專案清單的 voice-b: 403
    with pytest.raises(HTTPException) as exc_admin:
        resolve_tts_voice(
            admin_acc, env.runtime,
            requested_provider="cosyvoice",
            requested_voice="voice-b",
            project_id="proj-1",
        )
    assert exc_admin.value.status_code == 403

    # 4. ROOT 未指定聲音時：仍套用專案預設 voice-a
    auth_root_default = resolve_tts_voice(
        root_acc, env.runtime,
        requested_provider="",
        requested_voice="",
        project_id="proj-1",
    )
    assert auth_root_default is not None
    assert auth_root_default.resource_id == "voice-a"


def test_embed_key_strictly_bound_to_project_policy(env):
    """Embed 金鑰維持現有行為，不受 ROOT 豁免影響。"""
    embed_acc = _current(env.root, embed_key=env.embed_key)

    # 金鑰使用專案內預設聲音 voice-a 放行
    auth_embed = resolve_tts_voice(
        embed_acc, env.runtime,
        requested_provider="indextts",
        requested_voice="voice-a",
        project_id="proj-1",
    )
    assert auth_embed is not None
    assert auth_embed.resource_id == "voice-a"

    # 金鑰請求非金鑰或非專案允許之 voice-b: 拒絕
    with pytest.raises(HTTPException) as exc:
        resolve_tts_voice(
            embed_acc, env.runtime,
            requested_provider="cosyvoice",
            requested_voice="voice-b",
            project_id="proj-1",
        )
    assert exc.value.status_code in (403, 404)


def test_root_tts_fallback_and_taiwanese_routes(env):
    """TTS 備援與台語分流在 ROOT 呼叫時具備豁免權。"""
    # 專案沒有允許 edge-tts
    assert "edge-v" not in env.policy.allowed_tts_voices

    # ROOT 豁免：可退回 Edge
    assert tts_fallback_voice(env.runtime, env.policy, is_root=True) == ""
    # 一般使用者：不可默默換成 Edge
    assert tts_fallback_voice(env.runtime, env.policy, is_root=False) is None

    # 台語分流：專案清單只有 indextts，沒有 cosyvoice
    picked_root = project_voice_for_providers(
        env.runtime, env.policy, ("cosyvoice",), is_root=True
    )
    assert picked_root == ("cosyvoice", "")
    picked_non_root = project_voice_for_providers(
        env.runtime, env.policy, ("cosyvoice",), is_root=False
    )
    assert picked_non_root is None


def test_root_exempt_from_asr_policy(env):
    """ROOT 在批次與串流 ASR 皆不受專案政策限制，admin 與 member 受限。"""
    # 專案只允許 r2t2，breeze 為範圍外引擎
    # 1. 批次 ASR batch_asr_scope
    scope_root = batch_asr_scope(env.runtime, env.root, env.policy)
    assert "breeze" in scope_root.explicit
    assert "breeze" in scope_root.allowed

    scope_member = batch_asr_scope(env.runtime, env.member, env.policy)
    assert "breeze" not in scope_member.explicit
    assert "breeze" not in scope_member.allowed

    scope_admin = batch_asr_scope(env.runtime, env.admin, env.policy)
    assert "breeze" not in scope_admin.explicit
    assert "breeze" not in scope_admin.allowed

    # 2. 串流 ASR _engine_for
    assert asr_stream_engine_for(_current(env.root), "r2t2-live", env.policy, "proj-1") == "r2t2-live"
    # r2t2-live 不在專案清單（專案只允許 r2t2 批次），ROOT 豁免仍可使用，member 與 admin 則被擋
    assert asr_stream_engine_for(_current(env.root), "r2t2-live", env.policy, "proj-1") == "r2t2-live"
    assert asr_stream_engine_for(_current(env.member), "r2t2-live", env.policy, "proj-1") == ""
    assert asr_stream_engine_for(_current(env.admin), "r2t2-live", env.policy, "proj-1") == ""

    # 3. 有效 ASR effective_asr_engine
    env.runtime.account_access.set_asr_provider(env.root.id, "breeze")
    env.runtime.account_access.set_asr_provider(env.member.id, "breeze")
    assert effective_asr_engine(env.runtime, env.root, env.policy, project_id="proj-1") == "breeze"
    # member 偏好 breeze 被政策限制，退回專案預設 r2t2
    assert effective_asr_engine(env.runtime, env.member, env.policy, project_id="proj-1") == "r2t2"


def test_effective_project_resources_root_vs_member(env):
    """effective_project_resources 對 ROOT 回傳全部資源並標記 in_project_scope；對 member 僅回傳範圍內資源。"""
    # 角色 (char-a 在清單內，char-b 在清單外)
    chars_root = effective_project_resources(
        env.runtime, env.root, "proj-1", ResourceType.AVATAR_CHARACTER
    )
    scope_by_id = {e.resource_id: e.in_project_scope for e in chars_root}
    assert scope_by_id.get("char-a") is True
    assert scope_by_id.get("char-b") is False

    chars_member = effective_project_resources(
        env.runtime, env.member, "proj-1", ResourceType.AVATAR_CHARACTER
    )
    assert [e.resource_id for e in chars_member] == ["char-a"]
    assert chars_member[0].in_project_scope is True

    # 背景
    bgs_root = effective_project_resources(
        env.runtime, env.root, "proj-1", ResourceType.AVATAR_BACKGROUND
    )
    bg_scope = {e.resource_id: e.in_project_scope for e in bgs_root}
    assert bg_scope.get("bg-a") is True
    assert bg_scope.get("bg-b") is False

    bgs_member = effective_project_resources(
        env.runtime, env.member, "proj-1", ResourceType.AVATAR_BACKGROUND
    )
    assert [e.resource_id for e in bgs_member] == ["bg-a"]
    assert bgs_member[0].in_project_scope is True


def test_list_endpoints_in_project_scope_root_vs_member(env):
    """六個帶有 project_id 之清單端點對 ROOT 與一般使用者的 in_project_scope 標記驗證。"""
    headers_root = _headers(env, env.root)
    headers_member = _headers(env, env.member)

    # 1. /api/v1/projects/{id}/resources
    res_root = env.client.get("/api/v1/projects/proj-1/resources", headers=headers_root).json()
    char_scopes_root = {
        item["resource_id"]: item["in_project_scope"]
        for item in res_root[ResourceType.AVATAR_CHARACTER.value]
    }
    assert char_scopes_root["char-a"] is True
    assert char_scopes_root["char-b"] is False

    res_member = env.client.get("/api/v1/projects/proj-1/resources", headers=headers_member).json()
    assert [
        item["resource_id"] for item in res_member[ResourceType.AVATAR_CHARACTER.value]
    ] == ["char-a"]
    assert res_member[ResourceType.AVATAR_CHARACTER.value][0]["in_project_scope"] is True

    # 2. /api/v1/tts/providers?project_id=proj-1
    tts_root = env.client.get("/api/v1/tts/providers", params={"project_id": "proj-1"}, headers=headers_root).json()
    all_voice_items = [v for p in tts_root for v in p.get("voice_items", [])]
    voice_scope_root = {v["id"]: v["in_project_scope"] for v in all_voice_items}
    assert voice_scope_root.get("voice-a") is True
    assert voice_scope_root.get("voice-b") is False

    tts_member = env.client.get("/api/v1/tts/providers", params={"project_id": "proj-1"}, headers=headers_member).json()
    member_voices = [v for p in tts_member for v in p.get("voices", [])]
    assert member_voices == ["voice-a"]
    member_voice_items = [v for p in tts_member for v in p.get("voice_items", [])]
    assert all(v["in_project_scope"] is True for v in member_voice_items)

    # 3. /api/v1/avatar?project_id=proj-1
    avatar_root = env.client.get("/api/v1/avatar", params={"project_id": "proj-1"}, headers=headers_root).json()
    avatar_scope_root = {c["char_id"]: c["in_project_scope"] for c in avatar_root["characters"]}
    assert avatar_scope_root["char-a"] is True
    assert avatar_scope_root["char-b"] is False

    avatar_member = env.client.get("/api/v1/avatar", params={"project_id": "proj-1"}, headers=headers_member).json()
    assert [c["char_id"] for c in avatar_member["characters"]] == ["char-a"]
    assert avatar_member["characters"][0]["in_project_scope"] is True

    # 4. /api/v1/backgrounds?project_id=proj-1
    bg_root = env.client.get("/api/v1/backgrounds", params={"project_id": "proj-1"}, headers=headers_root).json()
    bg_scope_root = {b["background_id"]: b["in_project_scope"] for b in bg_root["backgrounds"]}
    assert bg_scope_root["bg-a"] is True
    assert bg_scope_root["bg-b"] is False

    bg_member = env.client.get("/api/v1/backgrounds", params={"project_id": "proj-1"}, headers=headers_member).json()
    assert [b["background_id"] for b in bg_member["backgrounds"]] == ["bg-a"]
    assert bg_member["backgrounds"][0]["in_project_scope"] is True

    # 5. /api/v1/avatar/mascots?project_id=proj-1
    mascot_root = env.client.get("/api/v1/avatar/mascots", params={"project_id": "proj-1"}, headers=headers_root).json()
    mascot_scope_root = {m["mascot_id"]: m["in_project_scope"] for m in mascot_root["mascots"]}
    assert mascot_scope_root["mascot-a"] is True
    assert mascot_scope_root["mascot-b"] is False

    mascot_member = env.client.get("/api/v1/avatar/mascots", params={"project_id": "proj-1"}, headers=headers_member).json()
    assert [m["mascot_id"] for m in mascot_member["mascots"]] == ["mascot-a"]
    assert mascot_member["mascots"][0]["in_project_scope"] is True

    # 6. /api/v1/me/capabilities?project_id=proj-1
    cap_root = env.client.get("/api/v1/me/capabilities", params={"project_id": "proj-1"}, headers=headers_root).json()
    asr_batch_root = {b["id"]: b["in_project_scope"] for b in cap_root["asr"]["batch"]}
    assert asr_batch_root.get("r2t2") is True
    assert asr_batch_root.get("breeze") is False

    cap_member = env.client.get("/api/v1/me/capabilities", params={"project_id": "proj-1"}, headers=headers_member).json()
    assert [b["id"] for b in cap_member["asr"]["batch"]] == ["r2t2"]
    assert cap_member["asr"]["batch"][0]["in_project_scope"] is True


def test_tts_cache_key_isolation(env):
    """ROOT 在有限制的專案合成的結果（含 Edge 備援）不能被成員命中。"""
    member_scope = tts._cache_scope("proj-1", env.policy, is_root=False)
    root_scope = tts._cache_scope("proj-1", env.policy, is_root=True)
    assert member_scope == "project:proj-1"
    assert root_scope == "project:proj-1:root"
    # 同一段文字、同一個「範圍內」聲音：ROOT 的結果也另存，因為它可能是 Edge 備援。
    assert make_cache_key("哈囉", "voice-a", "indextts", scope=member_scope) != make_cache_key(
        "哈囉", "voice-a", "indextts", scope=root_scope,
    )
    # 沒有聲音限制的專案維持共用的 key，命中率不變。
    assert tts._cache_scope("proj-1", None, is_root=True) == ""

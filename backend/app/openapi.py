"""Combine Backend route schemas with the proxied Brain OpenAPI contract."""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.auth.embed import is_allowlisted
from app.auth.middleware import is_auth_bypass_path
from app.config import get_tts_config
from app.http_client import SharedAsyncClient

logger = logging.getLogger("backend")
_health_http = SharedAsyncClient()
_BRAIN_OPENAPI_TIMEOUT_SECONDS = 5
# 限流掛在帳號 API key 驗證上，登入 session、Embed key 與免驗證的公開路由不計。
_API_KEY_RATE_LIMITED = {
    "description": (
        "以帳號 API key 呼叫時，同一把 key 在 60 秒滑動視窗內超過 "
        "API_KEY_RATE_LIMIT_PER_MINUTE 次（預設 300）；"
        "Retry-After 標頭為需等待的秒數。"
    ),
    "headers": {
        "Retry-After": {
            "description": "距離可再呼叫的秒數",
            "schema": {"type": "integer"},
        },
    },
}


def _with_account_authentication(schema: dict) -> dict:
    """Describe middleware auth after merging internal Brain contracts."""
    schema = deepcopy(schema)
    schemes = schema.setdefault("components", {}).setdefault(
        "securitySchemes", {},
    )
    schemes.update({
        "AccountBearer": {
            "type": "http", "scheme": "bearer",
            "bearerFormat": "JWT or ovk_<key_id>.<secret>",
            "description": "登入 token 或帳號 API key，沿用帳號權限。",
        },
        "SessionBearer": {
            "type": "http", "scheme": "bearer", "bearerFormat": "JWT",
            "description": "管理 API key 需要登入 token；不接受 API key。",
        },
        "AccountCookie": {
            "type": "apiKey", "in": "cookie", "name": "openvman_session",
            "description": "登入 session；寫入操作需要同來源 Origin。",
        },
        "EmbedKey": {
            "type": "apiKey", "in": "header", "name": "X-Embed-Key",
            "description": "網站嵌入專用，限制來源與可用路徑。",
        },
    })
    methods = {"get", "post", "put", "patch", "delete", "head", "options"}
    for path, operations in schema.get("paths", {}).items():
        for method, operation in operations.items():
            if method not in methods or not isinstance(operation, dict):
                continue
            if is_auth_bypass_path(path):
                # Public routes stay callable without Swagger's auth header;
                # internal routes retain their dedicated security contract.
                continue
            scheme = (
                "SessionBearer" if path.startswith("/api/v1/api-keys")
                else "AccountBearer"
            )
            operation["security"] = [{scheme: []}, {"AccountCookie": []}]
            if is_allowlisted(method, path):
                operation["security"].append({"EmbedKey": []})
            operation.setdefault("responses", {}).setdefault(
                "401", {"description": "憑證無效、過期、撤銷或帳號已停用"},
            )
            operation["responses"].setdefault(
                "403", {"description": "帳號／資源權限不足或驗證方式不允許"},
            )
            if scheme == "AccountBearer":
                operation["responses"].setdefault("429", _API_KEY_RATE_LIMITED)
    return schema


def _is_placeholder_response(response: object) -> bool:
    """FastAPI's default 200 for a route that declares nothing about its body."""
    if not isinstance(response, dict):
        return False
    content = response.get("content")
    return (
        response.get("description") == "Successful Response"
        and isinstance(content, dict)
        and all(
            isinstance(media, dict) and media.get("schema") in ({}, None)
            for media in content.values()
        )
    )


def _merge_responses(brain: dict, local: dict) -> dict:
    merged = {**brain, **local}
    # 代理路由沒有回應模型，只有 FastAPI 預設的空 schema；Brain 有寫的就用 Brain 的。
    for code, local_response in local.items():
        if code in brain and _is_placeholder_response(local_response):
            merged[code] = brain[code]
    return merged


def _merge_brain_openapi(base_schema: dict, brain_schema: dict) -> dict:
    merged = base_schema.copy()

    # Merge paths (remap /brain/ to /api/v1/)
    merged_paths = merged.get("paths", {})
    for path, path_item in brain_schema.get("paths", {}).items():
        if path.startswith("/brain/"):
            mapped_path = path.replace("/brain/", "/api/v1/", 1)
            local_path_item = merged_paths.get(mapped_path)
            if local_path_item is None:
                merged_paths[mapped_path] = path_item
                continue

            merged_path_item = path_item.copy()
            for key, local_value in local_path_item.items():
                brain_value = merged_path_item.get(key)
                if isinstance(brain_value, dict) and isinstance(local_value, dict):
                    # Brain fills missing schema fields while the Backend's
                    # public route metadata remains authoritative.
                    operation = {**brain_value, **local_value}
                    # 狀態碼逐一合併：Brain 的 422 等回應要留著，Backend
                    # 自己宣告的（專案 404、SSE 200）蓋過同碼的 Brain 版本。
                    if isinstance(brain_value.get("responses"), dict) and isinstance(
                        local_value.get("responses"), dict,
                    ):
                        operation["responses"] = _merge_responses(
                            brain_value["responses"], local_value["responses"],
                        )
                    merged_path_item[key] = operation
                else:
                    merged_path_item[key] = local_value
            merged_paths[mapped_path] = merged_path_item
    merged["paths"] = merged_paths

    # Merge components (schemas, securitySchemes, etc.)
    merged_comp = merged.get("components", {})
    for sec, vals in brain_schema.get("components", {}).items():
        merged_comp[sec] = {**merged_comp.get(sec, {}), **vals}
    merged["components"] = merged_comp

    # Merge tags
    tags_dict = {t["name"]: t for t in merged.get("tags", []) if "name" in t}
    for tag in brain_schema.get("tags", []):
        if name := tag.get("name"):
            tags_dict[name] = {**tags_dict.get(name, {}), **tag}
    merged["tags"] = list(tags_dict.values())

    return merged


async def _fetch_brain_openapi() -> dict | None:
    brain_openapi_url = f"{get_tts_config().brain_url}/brain/openapi.json"
    try:
        resp = await _health_http.get().get(brain_openapi_url, timeout=_BRAIN_OPENAPI_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("failed to fetch brain openapi from %s: %s", brain_openapi_url, exc)
        return None


class BackendOpenAPI:
    """Keep schema initialization state specific to the assembled application."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self._built = False

    async def build(self) -> dict:
        app = self.app
        if app.openapi_schema is not None:
            return app.openapi_schema
        local_schema = get_openapi(
            title=app.title, version=app.version, routes=app.routes,
        )
        if not self._built:
            brain_schema = await _fetch_brain_openapi()
            self._built = True
            if brain_schema is not None:
                app.openapi_schema = _with_account_authentication(
                    _merge_brain_openapi(local_schema, brain_schema),
                )
                return app.openapi_schema
        app.openapi_schema = _with_account_authentication(local_schema)
        return app.openapi_schema

    def schema(self) -> dict:
        app = self.app
        if app.openapi_schema is not None:
            return app.openapi_schema
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            local_schema = get_openapi(
                title=app.title, version=app.version, routes=app.routes,
            )
            loop.create_task(self.build())
            return _with_account_authentication(local_schema)
        return asyncio.run(self.build())

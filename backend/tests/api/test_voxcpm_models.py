import httpx
import pytest

from app.providers import voice_catalog


@pytest.mark.asyncio
async def test_voxcpm_models_lists_full_and_lora_entries_from_the_catalog(monkeypatch):
    catalog = {"engines": [
        {"id": "other", "models": [{"id": "lora::not-vox"}]},
        {"id": "voxcpm2", "models": [
            {"id": "full::ft-0820", "label": "ft-0820", "kind": "full", "loaded": True},
            {"id": "lora::vh387-hayley-mix", "label": "vh387-hayley-mix / latest", "kind": "lora"},
            {"id": "lora::vh387-orig-ep15", "label": "vh387-orig-ep15", "kind": "lora"},
            {"id": "lora::bad id"},
            "garbage",
        ]},
    ]}
    seen = {}

    class Client:
        async def get(self, url, **kwargs):
            seen["url"], seen["headers"] = url, kwargs.get("headers")
            return httpx.Response(200, json=catalog, request=httpx.Request("GET", url))

    monkeypatch.setattr(voice_catalog._http, "get", lambda: Client())

    models = await voice_catalog.fetch_voxcpm_models("http://vox/", "secret")

    assert seen == {
        "url": "http://vox/api/v1/catalog",
        "headers": {"Authorization": "Bearer secret"},
    }
    assert models == [
        {"id": "full::ft-0820", "label": "ft-0820", "kind": "full", "loaded": True},
        {"id": "lora::vh387-orig-ep15", "label": "vh387-orig-ep15", "kind": "lora", "loaded": False},
    ]


@pytest.mark.asyncio
async def test_voxcpm_models_is_empty_when_the_catalog_is_unreachable(monkeypatch):
    class Client:
        async def get(self, url, **kwargs):
            raise httpx.ConnectError("down")

    monkeypatch.setattr(voice_catalog._http, "get", lambda: Client())

    assert await voice_catalog.fetch_voxcpm_models("http://vox", "") == []

from __future__ import annotations

import httpx
import pytest


def _response(status_code: int, payload: object, url: str = "https://test.invalid") -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("GET", url),
    )


def _settings(**overrides):
    values = {
        "url2md_primary_url": "https://primary.invalid",
        "url2md_fallback_urls": "https://fallback-1.invalid,https://fallback-2.invalid",
        "web_search_max_chars": 3000,
        "web_search_max_results": 8,
    }
    values.update(overrides)
    return type("Settings", (), values)()


def test_search_web_uses_primary_and_normalizes_results(monkeypatch: pytest.MonkeyPatch):
    from tools.builtin import web_tools

    calls: list[tuple[str, dict[str, str]]] = []

    class FakeClient:
        def request(self, method, url, *, params, headers):
            assert method == "GET"
            calls.append((url, params))
            return _response(
                200,
                {
                    "code": 200,
                    "status": 200,
                    "data": [
                        {"title": "Example", "url": "https://example.com", "description": "A page"}
                    ],
                },
                url,
            )

    monkeypatch.setattr(web_tools, "get_settings", lambda: _settings())
    monkeypatch.setattr(web_tools, "_get_url2md_client", lambda: FakeClient())

    result = web_tools._search_web({"query": "OpenAI"})

    assert calls == [("https://primary.invalid/search", {"q": "OpenAI"})]
    assert result["query"] == "OpenAI"
    assert result["results"] == [
        {"title": "Example", "url": "https://example.com", "description": "A page", "content": ""}
    ]
    assert result["citations"] == [{"title": "Example", "url": "https://example.com"}]


def test_read_web_page_falls_back_when_primary_fails(monkeypatch: pytest.MonkeyPatch):
    from tools.builtin import web_tools

    calls: list[str] = []

    class FakeClient:
        def request(self, method, url, *, params=None, headers=None):
            assert method == "GET"
            calls.append(url)
            if "primary" in url:
                raise httpx.ConnectError("primary unavailable", request=httpx.Request("GET", url))
            return _response(
                200,
                {"code": 200, "status": 20000, "data": {
                    "title": "Example", "url": "https://example.com/", "content": "hello"
                }},
                url,
            )

    monkeypatch.setattr(web_tools, "get_settings", lambda: _settings())
    monkeypatch.setattr(web_tools, "_get_url2md_client", lambda: FakeClient())

    result = web_tools._read_web_page({"url": "https://example.com"})

    assert calls == [
        "https://primary.invalid/https://example.com",
        "https://fallback-1.invalid/https://example.com",
    ]
    assert result["content"] == "hello"
    assert result["provider"] == "https://fallback-1.invalid"


def test_web_tools_reject_invalid_url_and_empty_query(monkeypatch: pytest.MonkeyPatch):
    from tools.builtin import web_tools

    monkeypatch.setattr(web_tools, "get_settings", lambda: _settings())

    with pytest.raises(ValueError, match="query 不可為空"):
        web_tools._search_web({"query": "  "})
    with pytest.raises(ValueError, match="無效的網址"):
        web_tools._read_web_page({"url": "file:///tmp/secret"})
    with pytest.raises(ValueError, match="內部|特殊"):
        web_tools._read_web_page({"url": "http://127.0.0.1:8200/metrics"})

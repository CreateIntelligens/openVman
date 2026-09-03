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


def _fake_client(items):
    class FakeClient:
        def request(self, method, url, *, params, headers):
            return _response(200, {"code": 200, "status": 200, "data": items}, url)

    return FakeClient()


def test_search_web_drops_blocked_domains(monkeypatch: pytest.MonkeyPatch):
    from tools.builtin import web_tools

    monkeypatch.setattr(
        web_tools,
        "get_settings",
        lambda: _settings(web_search_blocked_domains="wikipedia.org", web_search_min_relevance=0, web_search_relevance_ratio=0),
    )
    monkeypatch.setattr(web_tools, "_get_url2md_client", lambda: _fake_client([
        {"title": "麥當勞 - 維基百科", "url": "https://zh.wikipedia.org/wiki/McD", "description": "百科"},
        {"title": "內湖速食清單", "url": "https://example.com/neihu", "description": "在地"},
    ]))

    result = web_tools._search_web({"query": "內湖 速食店"})

    assert [r["url"] for r in result["results"]] == ["https://example.com/neihu"]


def test_search_web_reranks_by_relevance_and_drops_the_weak_tail(monkeypatch: pytest.MonkeyPatch):
    from tools.builtin import web_tools

    monkeypatch.setattr(
        web_tools,
        "get_settings",
        lambda: _settings(web_search_min_relevance=0.15, web_search_relevance_ratio=0.7),
    )
    monkeypatch.setattr(web_tools, "_get_url2md_client", lambda: _fake_client([
        {"title": "麥當勞 - 維基百科", "url": "https://a.invalid", "description": "全球連鎖歷史"},
        {"title": "內湖舊宗路速食店整理", "url": "https://b.invalid", "description": "在地清單"},
        {"title": "內湖美食", "url": "https://c.invalid", "description": "含速食"},
    ]))
    # 第 2 筆最貼近問題，第 3 筆次之，第 1 筆（百科）幾乎無關
    monkeypatch.setattr(
        web_tools,
        "_embed_for_rerank",
        lambda anchor, docs: ([1.0, 0.0], [[0.05, 1.0], [1.0, 0.0], [0.8, 0.6]]),
    )

    result = web_tools._search_web({"query": "內湖 舊宗路 速食店"})

    assert [r["url"] for r in result["results"]] == ["https://b.invalid", "https://c.invalid"]
    assert result["results"][0]["relevance"] == 1.0
    assert [c["url"] for c in result["citations"]] == ["https://b.invalid", "https://c.invalid"]


def test_search_web_keeps_engine_order_when_rerank_fails(monkeypatch: pytest.MonkeyPatch):
    from tools.builtin import web_tools

    monkeypatch.setattr(web_tools, "get_settings", lambda: _settings(web_search_min_relevance=0.15))
    monkeypatch.setattr(web_tools, "_get_url2md_client", lambda: _fake_client([
        {"title": "A", "url": "https://a.invalid", "description": ""},
        {"title": "B", "url": "https://b.invalid", "description": ""},
    ]))

    def _boom(anchor, docs):
        raise RuntimeError("embedding down")

    monkeypatch.setattr(web_tools, "_embed_for_rerank", _boom)

    result = web_tools._search_web({"query": "anything"})

    assert [r["url"] for r in result["results"]] == ["https://a.invalid", "https://b.invalid"]

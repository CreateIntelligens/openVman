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
        "web_read_max_urls": 5,
        "url2md_total_budget_s": 20.0,
        "url2md_circuit_cooldown_s": 60.0,
    }
    values.update(overrides)
    return type("Settings", (), values)()


def test_search_web_uses_primary_and_normalizes_results(monkeypatch: pytest.MonkeyPatch):
    from tools.builtin import web_tools

    calls: list[tuple[str, dict[str, str]]] = []

    class FakeClient:
        def request(self, method, url, **kwargs):
            assert method == "GET"
            calls.append((url, kwargs.get("params")))
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

    monkeypatch.setattr(web_tools, "mode_settings", lambda: _settings())
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
        def request(self, method, url, **kwargs):
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

    monkeypatch.setattr(web_tools, "mode_settings", lambda: _settings())
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

    monkeypatch.setattr(web_tools, "mode_settings", lambda: _settings())

    with pytest.raises(ValueError, match="query 不可為空"):
        web_tools._search_web({"query": "  "})
    with pytest.raises(ValueError, match="無效的網址"):
        web_tools._read_web_page({"url": "file:///tmp/secret"})
    with pytest.raises(ValueError, match="內部|特殊"):
        web_tools._read_web_page({"url": "http://127.0.0.1:8200/metrics"})


def _fake_client(items):
    class FakeClient:
        def request(self, method, url, **kwargs):
            return _response(200, {"code": 200, "status": 200, "data": items}, url)

    return FakeClient()


def test_search_web_drops_blocked_domains(monkeypatch: pytest.MonkeyPatch):
    from tools.builtin import web_tools

    monkeypatch.setattr(
        web_tools,
        "mode_settings",
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
        "mode_settings",
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

    monkeypatch.setattr(web_tools, "mode_settings", lambda: _settings(web_search_min_relevance=0.15))
    monkeypatch.setattr(web_tools, "_get_url2md_client", lambda: _fake_client([
        {"title": "A", "url": "https://a.invalid", "description": ""},
        {"title": "B", "url": "https://b.invalid", "description": ""},
    ]))

    def _boom(anchor, docs):
        raise RuntimeError("embedding down")

    monkeypatch.setattr(web_tools, "_embed_for_rerank", _boom)

    result = web_tools._search_web({"query": "anything"})

    assert [r["url"] for r in result["results"]] == ["https://a.invalid", "https://b.invalid"]


def test_read_web_page_batches_multiple_urls_into_one_request(monkeypatch: pytest.MonkeyPatch):
    """多個網址要併成一個 /v1/batch 請求，而不是各發一次 GET。"""
    from tools.builtin import web_tools

    calls: list[tuple[str, str, object]] = []

    class FakeClient:
        def request(self, method, url, **kwargs):
            calls.append((method, url, kwargs.get("json")))
            # 批次端點比單頁多包一層 data。
            return _response(200, {"code": 200, "status": 200, "data": {"data": [
                {"title": "One", "url": "https://example.com/", "content": "aaa"},
                {"title": "Two", "url": "https://www.iana.org/", "content": "bbb"},
            ]}}, url)

    monkeypatch.setattr(web_tools, "mode_settings", lambda: _settings())
    monkeypatch.setattr(web_tools, "_get_url2md_client", lambda: FakeClient())

    result = web_tools._read_web_page(
        {"urls": ["https://example.com", "https://www.iana.org"]}
    )

    assert len(calls) == 1
    method, url, body = calls[0]
    assert method == "POST"
    assert url == "https://primary.invalid/v1/batch"
    assert body == {"urls": ["https://example.com", "https://www.iana.org"]}
    assert result["count"] == 2
    assert [page["content"] for page in result["pages"]] == ["aaa", "bbb"]


def test_read_web_page_keeps_flat_shape_for_a_single_url(monkeypatch: pytest.MonkeyPatch):
    """單一網址仍走單頁端點並回平面形狀，既有呼叫端不受影響。"""
    from tools.builtin import web_tools

    calls: list[tuple[str, str]] = []

    class FakeClient:
        def request(self, method, url, **kwargs):
            calls.append((method, url))
            return _response(200, {"code": 200, "status": 200, "data": {
                "title": "One", "url": "https://example.com/", "content": "aaa"
            }}, url)

    monkeypatch.setattr(web_tools, "mode_settings", lambda: _settings())
    monkeypatch.setattr(web_tools, "_get_url2md_client", lambda: FakeClient())

    result = web_tools._read_web_page({"urls": ["https://example.com"]})

    assert calls == [("GET", "https://primary.invalid/https://example.com")]
    assert result["content"] == "aaa"
    assert "pages" not in result


def test_read_web_page_maps_results_back_by_url_when_one_fails(
    monkeypatch: pytest.MonkeyPatch,
):
    """上游對每筆各自容錯：少回的那筆要被跳過，而不是錯位對到別人的內容。"""
    from tools.builtin import web_tools

    class FakeClient:
        def request(self, method, url, **kwargs):
            # 只回第二個網址，第一個在上游失敗了。
            return _response(200, {"code": 200, "status": 200, "data": {"data": [
                {"title": "Two", "url": "https://www.iana.org/", "content": "bbb"},
            ]}}, url)

    monkeypatch.setattr(web_tools, "mode_settings", lambda: _settings())
    monkeypatch.setattr(web_tools, "_get_url2md_client", lambda: FakeClient())

    result = web_tools._read_web_page(
        {"urls": ["https://example.com", "https://www.iana.org"]}
    )

    assert result["count"] == 1
    assert result["pages"][0]["url"] == "https://www.iana.org/"
    assert result["pages"][0]["content"] == "bbb"


def test_read_web_page_batch_falls_back_to_next_provider(monkeypatch: pytest.MonkeyPatch):
    """批次讀取失敗時要走 fallback chain，跟單頁一樣。"""
    from tools.builtin import web_tools

    calls: list[str] = []

    class FakeClient:
        def request(self, method, url, **kwargs):
            calls.append(url)
            if "primary" in url:
                raise httpx.ConnectError("down", request=httpx.Request("POST", url))
            return _response(200, {"code": 200, "status": 200, "data": {"data": [
                {"title": "One", "url": "https://example.com/", "content": "aaa"},
                {"title": "Two", "url": "https://www.iana.org/", "content": "bbb"},
            ]}}, url)

    monkeypatch.setattr(web_tools, "mode_settings", lambda: _settings())
    monkeypatch.setattr(web_tools, "_get_url2md_client", lambda: FakeClient())

    result = web_tools._read_web_page(
        {"urls": ["https://example.com", "https://www.iana.org"]}
    )

    assert calls == [
        "https://primary.invalid/v1/batch",
        "https://fallback-1.invalid/v1/batch",
    ]
    assert result["provider"] == "https://fallback-1.invalid"


def test_read_web_page_rejects_too_many_urls(monkeypatch: pytest.MonkeyPatch):
    from tools.builtin import web_tools

    monkeypatch.setattr(web_tools, "mode_settings", lambda: _settings(web_read_max_urls=2))

    with pytest.raises(ValueError, match="最多讀取 2 個網址"):
        web_tools._read_web_page({"urls": [
            "https://example.com", "https://www.iana.org", "https://www.example.net",
        ]})


def test_read_web_page_deduplicates_urls(monkeypatch: pytest.MonkeyPatch):
    """同一個網址重複帶進來只讀一次，避免浪費上游額度。"""
    from tools.builtin import web_tools

    monkeypatch.setattr(web_tools, "mode_settings", lambda: _settings())

    urls = web_tools._normalize_read_urls(
        {"urls": ["https://example.com", "https://example.com"]}
    )

    assert urls == ["https://example.com"]


@pytest.fixture(autouse=True)
def _clean_circuits():
    """斷路器狀態存在模組層級，測試之間必須清乾淨。"""
    from tools.builtin import web_tools

    web_tools.reset_url2md_circuits()
    yield
    web_tools.reset_url2md_circuits()


def test_failed_host_is_skipped_while_its_circuit_is_open(monkeypatch: pytest.MonkeyPatch):
    """一台掛掉後，冷卻期內的後續請求要直接跳過它，不再付一次逾時代價。"""
    from tools.builtin import web_tools

    attempted: list[str] = []

    class FakeClient:
        def request(self, method, url, *, json=None, headers=None, params=None, timeout=None):
            attempted.append(url)
            if "primary" in url:
                raise httpx.ConnectError("down", request=httpx.Request("GET", url))
            return _response(200, {"code": 200, "status": 200, "data": []}, url)

    monkeypatch.setattr(web_tools, "mode_settings", lambda: _settings(
        web_search_min_relevance=0, web_search_relevance_ratio=0,
    ))
    monkeypatch.setattr(web_tools, "_get_url2md_client", lambda: FakeClient())

    web_tools._search_web({"query": "one"})
    first_round = list(attempted)
    attempted.clear()
    web_tools._search_web({"query": "two"})

    # 第一輪要先撞到 primary 才知道它掛了。
    assert any("primary" in url for url in first_round)
    # 第二輪不該再碰 primary。
    assert not any("primary" in url for url in attempted)


def test_circuit_reopens_after_the_cooldown_expires(monkeypatch: pytest.MonkeyPatch):
    """冷卻結束後要重新嘗試，否則上游復原了也永遠不會用回主要主機。"""
    from tools.builtin import web_tools

    monkeypatch.setattr(web_tools, "mode_settings", lambda: _settings(
        url2md_circuit_cooldown_s=0.01,
    ))
    web_tools._note_failure("https://primary.invalid")

    assert web_tools._is_circuit_open("https://primary.invalid", 60.0)

    import time as _time
    _time.sleep(0.02)

    assert not web_tools._is_circuit_open("https://primary.invalid", 0.01)


def test_all_hosts_in_cooldown_still_get_tried(monkeypatch: pytest.MonkeyPatch):
    """全部都在冷卻中時仍要整條鏈試一遍，寧可慢也不要在上游已復原時直接放棄。"""
    from tools.builtin import web_tools

    attempted: list[str] = []

    class FakeClient:
        def request(self, method, url, *, json=None, headers=None, params=None, timeout=None):
            attempted.append(url)
            return _response(200, {"code": 200, "status": 200, "data": []}, url)

    cfg = _settings(web_search_min_relevance=0, web_search_relevance_ratio=0)
    monkeypatch.setattr(web_tools, "mode_settings", lambda: cfg)
    monkeypatch.setattr(web_tools, "_get_url2md_client", lambda: FakeClient())
    for base in web_tools._url2md_bases():
        web_tools._note_failure(base)

    web_tools._search_web({"query": "q"})

    assert len(attempted) == 1  # 第一台就成功了，但它本來是被冷卻的


def test_budget_caps_the_per_host_timeout(monkeypatch: pytest.MonkeyPatch):
    """每台的逾時不能超過整條鏈的剩餘預算。"""
    from tools.builtin import web_tools

    seen_timeouts: list[object] = []

    class FakeClient:
        def request(self, method, url, *, json=None, headers=None, params=None, timeout=None):
            seen_timeouts.append(timeout)
            return _response(200, {"code": 200, "status": 200, "data": []}, url)

    monkeypatch.setattr(web_tools, "mode_settings", lambda: _settings(
        url2md_total_budget_s=3.0,
        web_search_min_relevance=0,
        web_search_relevance_ratio=0,
    ))
    monkeypatch.setattr(web_tools, "_get_url2md_client", lambda: FakeClient())

    web_tools._search_web({"query": "q"})

    assert seen_timeouts, "應該有帶 timeout 下去"
    timeout = seen_timeouts[0]
    assert timeout is not None
    # 讀取逾時要被壓到預算內，不能還是預設的 25 秒。
    assert timeout.read <= 3.0


def test_chain_stops_once_the_budget_is_exhausted(monkeypatch: pytest.MonkeyPatch):
    """預算用完就不再試下一台，避免三台各自逾時累加。

    每次呼叫都讓時鐘前進，模擬真實的「掛在那裡等逾時」；預算 3 秒、每台耗掉
    2 秒，所以第二台之後就不該再試。
    """
    from tools.builtin import web_tools

    attempted: list[str] = []
    clock = {"now": 1000.0}

    class FakeClient:
        def request(self, method, url, **kwargs):
            attempted.append(url)
            clock["now"] += 2.0  # 這一台「花了」兩秒才逾時
            raise httpx.ReadTimeout("hang", request=httpx.Request("GET", url))

    monkeypatch.setattr(web_tools.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(web_tools, "mode_settings", lambda: _settings(
        url2md_total_budget_s=3.0, url2md_circuit_cooldown_s=0,
    ))
    monkeypatch.setattr(web_tools, "_get_url2md_client", lambda: FakeClient())

    with pytest.raises(ValueError, match="fallback chain"):
        web_tools._search_web({"query": "q"})

    # 第一台花掉 2 秒，剩 1 秒還能試第二台；第二台之後預算就沒了。
    assert len(attempted) == 2


def test_read_web_page_tolerates_tool_argument_drift(monkeypatch: pytest.MonkeyPatch):
    """模型偏離 schema 時不該讓整個工具呼叫失敗，只要意思還清楚。"""
    from tools.builtin import web_tools

    monkeypatch.setattr(web_tools, "mode_settings", lambda: _settings())
    expected = ["https://example.com"]

    # 舊版的單一 url、把陣列送成字串、空 urls 配上 url、陣列裡混進 None
    # 或空字串——都視為同一個意思。
    assert web_tools._normalize_read_urls({"url": "https://example.com"}) == expected
    assert web_tools._normalize_read_urls({"urls": "https://example.com"}) == expected
    assert web_tools._normalize_read_urls(
        {"urls": [], "url": "https://example.com"}
    ) == expected
    assert web_tools._normalize_read_urls(
        {"urls": ["https://example.com", None, "  "]}
    ) == expected


def test_read_web_page_still_rejects_genuinely_bad_input(monkeypatch: pytest.MonkeyPatch):
    """容忍的是外層形狀，不是內容：無效網址仍要擋下來。"""
    from tools.builtin import web_tools

    monkeypatch.setattr(web_tools, "mode_settings", lambda: _settings())

    with pytest.raises(ValueError, match="url 不可為空"):
        web_tools._normalize_read_urls({"urls": [None, ""]})
    with pytest.raises(ValueError, match="無效的網址"):
        # JSON 字串沒有被解析——它不是網址，不該偷偷放行。
        web_tools._normalize_read_urls({"urls": '["https://example.com"]'})
    with pytest.raises(ValueError, match="內部|特殊"):
        web_tools._normalize_read_urls({"url": "http://127.0.0.1:8200/metrics"})

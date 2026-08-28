from __future__ import annotations

import httpx
import pytest


def _settings(**overrides):
    values = {
        "wiki_api_base_url": "https://wiki.invalid/api",
        "wiki_publish_max_chars": 100000,
        "wiki_publish_timeout_seconds": 30,
    }
    values.update(overrides)
    return type("Settings", (), values)()


def test_publish_wiki_returns_only_public_share_url(monkeypatch: pytest.MonkeyPatch):
    from tools.builtin import wiki_tools

    captured: dict[str, object] = {}

    class FakeClient:
        def post(self, url, *, headers, json):
            captured["url"] = url
            captured["json"] = json
            return httpx.Response(
                200,
                json={
                    "data": {
                        "url": "https://wiki.invalid/edit/report",
                        "shareUrl": "https://wiki.invalid/share/abc123",
                    }
                },
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(wiki_tools, "get_settings", lambda: _settings())
    monkeypatch.setattr(wiki_tools, "_get_wiki_client", lambda: FakeClient())

    result = wiki_tools._publish_wiki({
        "path": "reports/openvman",
        "markdown": "# Report\n\nDone.",
    })

    assert captured == {
        "url": "https://wiki.invalid/api/reports/openvman",
        "json": {
            "text": "# Report\n\nDone.",
            "public": True,
            "share": True,
        },
    }
    assert result == {
        "path": "reports/openvman",
        "shareUrl": "https://wiki.invalid/share/abc123",
        "public": True,
        "append": False,
    }
    assert "url" not in result


def test_publish_wiki_rejects_unsafe_path_and_oversized_markdown(monkeypatch: pytest.MonkeyPatch):
    from tools.builtin import wiki_tools

    monkeypatch.setattr(wiki_tools, "get_settings", lambda: _settings(wiki_publish_max_chars=5))

    with pytest.raises(ValueError, match="無效的 Wiki path"):
        wiki_tools._publish_wiki({"path": "../private", "markdown": "ok"})
    with pytest.raises(ValueError, match="內容過長"):
        wiki_tools._publish_wiki({"path": "report", "markdown": "too long"})

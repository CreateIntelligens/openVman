"""Tests for memory.query_expansion — LLM-based semantic query expansion."""

from __future__ import annotations

from unittest.mock import patch

from memory.query_expansion import expand_query, parse_expansion_terms


_LLM_PATH = "core.llm_client.generate_chat_reply"


class TestParseExpansionTerms:
    def test_one_term_per_line(self):
        terms = parse_expansion_terms("退款流程\n申請退費\n款項返還", "怎麼退費", 3)
        assert terms == ["退款流程", "申請退費", "款項返還"]

    def test_strips_bullets_and_numbering(self):
        raw = "1. 退款流程\n- 申請退費\n* 款項返還"
        terms = parse_expansion_terms(raw, "怎麼退費", 3)
        assert terms == ["退款流程", "申請退費", "款項返還"]

    def test_caps_at_max_terms(self):
        raw = "a\nb\nc\nd\ne"
        assert parse_expansion_terms(raw, "q", 3) == ["a", "b", "c"]

    def test_drops_duplicates_and_original_query(self):
        raw = "退款流程\n退款流程\n怎麼退費"
        assert parse_expansion_terms(raw, "怎麼退費", 3) == ["退款流程"]

    def test_digit_leading_term_is_not_mangled(self):
        terms = parse_expansion_terms("1. 3D列印\n2、樂高 42100\n- 增材製造", "q", 3)
        assert terms == ["3D列印", "樂高 42100", "增材製造"]

    def test_none_sentinel_returns_empty(self):
        assert parse_expansion_terms("NONE", "q", 3) == []

    def test_blank_reply_returns_empty(self):
        assert parse_expansion_terms("", "q", 3) == []
        assert parse_expansion_terms("  \n  ", "q", 3) == []


class TestExpandQuery:
    def test_returns_parsed_terms(self):
        with patch(_LLM_PATH, return_value="退款流程\n申請退費"):
            assert expand_query("怎麼退費", max_terms=3) == ["退款流程", "申請退費"]

    def test_llm_failure_returns_empty(self):
        with patch(_LLM_PATH, side_effect=RuntimeError("provider down")):
            assert expand_query("怎麼退費", max_terms=3) == []

    def test_empty_query_skips_llm(self):
        with patch(_LLM_PATH) as mock_llm:
            assert expand_query("   ", max_terms=3) == []
            mock_llm.assert_not_called()

    def test_zero_max_terms_skips_llm(self):
        with patch(_LLM_PATH) as mock_llm:
            assert expand_query("q", max_terms=0) == []
            mock_llm.assert_not_called()


class TestSearchRouteGating:
    """routes.search._maybe_expand_query 的開關邏輯。"""

    @staticmethod
    def _payload(query_type="hybrid", expand=False):
        from protocol.schemas import SearchRequest

        return SearchRequest(query="q", query_type=query_type, expand=expand)

    @staticmethod
    def _config(enabled=False):
        import types

        return types.SimpleNamespace(
            rag_query_expansion_enabled=enabled,
            rag_query_expansion_max_terms=3,
            rag_query_expansion_model="",
        )

    def _run(self, monkeypatch, payload, enabled=False):
        import config as config_mod
        import memory.query_expansion as qe
        from routes.search import _maybe_expand_query

        monkeypatch.setattr(config_mod, "get_settings", lambda: self._config(enabled))
        monkeypatch.setattr(qe, "expand_query", lambda q, **k: ["擴展詞"])
        return _maybe_expand_query("q", payload, trace_id="t")

    def test_expand_flag_triggers_expansion(self, monkeypatch):
        assert self._run(monkeypatch, self._payload(expand=True)) == ["擴展詞"]

    def test_global_config_triggers_expansion(self, monkeypatch):
        assert self._run(monkeypatch, self._payload(), enabled=True) == ["擴展詞"]

    def test_off_by_default(self, monkeypatch):
        assert self._run(monkeypatch, self._payload()) == []

    def test_vector_only_query_never_expands(self, monkeypatch):
        payload = self._payload(query_type="vector", expand=True)
        assert self._run(monkeypatch, payload) == []

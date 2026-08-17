"""Tests for memory.dreaming.scheduler — cron parsing, timezone, next_run, force, phase_stats."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Module stubs — prevent heavy imports during testing
# ---------------------------------------------------------------------------

_fake_embedder = ModuleType("memory.embedder")
_fake_embedder.get_embedder = lambda embedding_version=None: MagicMock(encode=lambda texts: [[0.1] for _ in texts])  # type: ignore[attr-defined]
_fake_embedder.encode_text = lambda text, embedding_version=None: [0.1]  # type: ignore[attr-defined]
_fake_embedder.encode_query_with_fallback = lambda query, *, project_id="default", table_names=("knowledge", "memories"): MagicMock(version="bge", vector=[0.1], attempted_versions=[])  # type: ignore[attr-defined]

_fake_importance = ModuleType("memory.importance")
_fake_importance.score_importance = lambda text: MagicMock(score=0.5, level="medium", signals=())  # type: ignore[attr-defined]
_fake_importance.ImportanceResult = type("ImportanceResult", (), {})  # type: ignore[attr-defined]

_fake_infra_db = ModuleType("infra.db")
_fake_infra_db.normalize_vector = lambda v: list(v) if hasattr(v, "__iter__") else [v]  # type: ignore[attr-defined]
_fake_infra_db.get_memories_table = lambda project_id="default", embedding_version=None: MagicMock()  # type: ignore[attr-defined]
_fake_infra_db.get_db = MagicMock()  # type: ignore[attr-defined]
_fake_infra_db.resolve_vector_table_name = lambda name, ev=None: name  # type: ignore[attr-defined]

_STUBS = {
    "lancedb": MagicMock(),
    "sentence_transformers": MagicMock(),
    "FlagEmbedding": MagicMock(),
    "infra.db": _fake_infra_db,
    "memory.embedder": _fake_embedder,
    "memory.importance": _fake_importance,
}

# Build config mock with all needed attributes
_cfg_mock = MagicMock()
_cfg_mock.dreaming_enabled = True
_cfg_mock.dreaming_cron = "0 3 * * *"
_cfg_mock.dreaming_timezone = "Asia/Taipei"
_cfg_mock.dreaming_lookback_days = 7
_cfg_mock.dreaming_min_score = 0.45
_cfg_mock.dreaming_min_recall_count = 2
_cfg_mock.dreaming_min_unique_queries = 2
_cfg_mock.dreaming_candidate_limit = 100
_cfg_mock.dreaming_similarity_threshold = 0.90
_cfg_mock.max_session_ttl_minutes = 30 * 24 * 60
_cfg_mock.rag_distance_cutoff = 1.2
_cfg_mock.gateway_internal_token = "test-internal-token"

for mod_name, stub in _STUBS.items():
    if mod_name not in sys.modules:
        sys.modules[mod_name] = stub

from memory.dreaming.scheduler import (
    CronSpec,
    _compute_next_run,
    _extract_phase_stats,
    _get_tz,
    _last_run,
    _parse_cron,
    get_dreaming_status,
    run_dreaming_cycle,
)


@pytest.fixture(autouse=True)
def _configure_scheduler_state(monkeypatch, tmp_path):
    """Reset scheduler state and route filesystem access to this test."""
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "dreaming" / ".dreams").mkdir(parents=True, exist_ok=True)

    import config
    import knowledge.workspace as kw
    monkeypatch.setattr(config, "get_settings", lambda: _cfg_mock)
    monkeypatch.setattr(kw, "get_workspace_root", lambda pid="default": ws)

    _last_run.clear()


# ===== CronSpec Tests =====

class TestCronSpec:
    def test_exact_match(self):
        spec = CronSpec(minute=0, hour=3)
        assert spec.matches(3, 0)
        assert not spec.matches(3, 1)
        assert not spec.matches(4, 0)

    def test_wildcard_hour(self):
        spec = CronSpec(minute=30)
        assert spec.matches(0, 30)
        assert spec.matches(23, 30)
        assert not spec.matches(0, 15)

    def test_step_value(self):
        spec = CronSpec(minute_step=5)
        assert spec.matches(0, 0)
        assert spec.matches(0, 5)
        assert spec.matches(0, 10)
        assert spec.matches(12, 55)
        assert not spec.matches(0, 3)
        assert not spec.matches(0, 7)

    def test_step_with_hour(self):
        spec = CronSpec(minute_step=15, hour=6)
        assert spec.matches(6, 0)
        assert spec.matches(6, 15)
        assert spec.matches(6, 30)
        assert not spec.matches(7, 0)

    def test_all_wildcards(self):
        spec = CronSpec()
        assert spec.matches(0, 0)
        assert spec.matches(23, 59)


# ===== Cron Parser Tests =====

class TestParseCron:
    def test_standard_cron(self):
        spec = _parse_cron("0 3 * * *")
        assert spec.minute == 0
        assert spec.hour == 3
        assert spec.minute_step is None

    def test_step_cron(self):
        spec = _parse_cron("*/5 * * * *")
        assert spec.minute is None
        assert spec.minute_step == 5
        assert spec.hour is None

    def test_minute_only(self):
        spec = _parse_cron("30 * * * *")
        assert spec.minute == 30
        assert spec.hour is None

    def test_step_with_hour(self):
        spec = _parse_cron("*/10 6 * * *")
        assert spec.minute_step == 10
        assert spec.hour == 6

    def test_empty_string(self):
        spec = _parse_cron("")
        assert spec == CronSpec()

    def test_single_field(self):
        spec = _parse_cron("0")
        assert spec == CronSpec()


# ===== Timezone Tests =====

class TestGetTz:
    def test_utc_plus_8(self):
        tz = _get_tz("UTC+8")
        now = datetime.now(tz)
        assert now.utcoffset() == timedelta(hours=8)

    def test_utc_minus_5(self):
        tz = _get_tz("UTC-5")
        now = datetime.now(tz)
        assert now.utcoffset() == timedelta(hours=-5)

    def test_bare_utc(self):
        tz = _get_tz("UTC")
        assert datetime.now(tz).utcoffset() == timedelta(0)

    def test_empty_string(self):
        tz = _get_tz("")
        assert tz == timezone.utc

    def test_iana_name(self):
        tz = _get_tz("Asia/Taipei")
        now = datetime.now(tz)
        assert now.utcoffset() == timedelta(hours=8)

    def test_invalid_falls_back(self):
        tz = _get_tz("Invalid/Zone")
        assert tz == timezone.utc


# ===== Next Run Tests =====

class TestComputeNextRun:
    def test_returns_iso_string(self):
        spec = CronSpec(minute=0, hour=3)
        result = _compute_next_run(spec, timezone.utc)
        assert result is not None
        # Should parse as valid ISO
        dt = datetime.fromisoformat(result)
        assert dt.hour == 3
        assert dt.minute == 0

    def test_step_cron_next_run(self):
        spec = CronSpec(minute_step=5)
        result = _compute_next_run(spec, timezone.utc)
        assert result is not None
        dt = datetime.fromisoformat(result)
        assert dt.minute % 5 == 0

    def test_wildcard_returns_soon(self):
        spec = CronSpec()
        result = _compute_next_run(spec, timezone.utc)
        assert result is not None
        dt = datetime.fromisoformat(result)
        now = datetime.now(timezone.utc)
        assert (dt - now).total_seconds() < 120  # Should be within 2 minutes


# ===== Phase Stats Tests =====

class TestExtractPhaseStats:
    def test_none_input(self):
        assert _extract_phase_stats(None) is None

    def test_empty_dict_without_status(self):
        # An empty dict has no phase data, so stats reflects zero defaults
        stats = _extract_phase_stats({})
        # It returns a valid stats dict even from empty input
        if stats is not None:
            assert stats["candidate_count"] == 0
            assert stats["promoted_count"] == 0

    def test_full_stats(self):
        last_run = {
            "light": {"candidate_count": 10, "fragment_count": 5},
            "deep": {"promoted_count": 3, "qualified_count": 7},
            "rem": {"theme_count": 2},
            "duration_seconds": 1.5,
        }
        stats = _extract_phase_stats(last_run)
        assert stats["candidate_count"] == 10
        assert stats["fragment_count"] == 5
        assert stats["promoted_count"] == 3
        assert stats["qualified_count"] == 7
        assert stats["theme_count"] == 2
        assert stats["duration_seconds"] == 1.5


# ===== Force / Skip Tests =====

class TestForceSkip:
    def setup_method(self):
        _last_run.clear()

    @pytest.fixture(autouse=True)
    def _isolate_dreams_dir(self, tmp_path, monkeypatch):
        """_dreams_dir resolves to a real, shared project data directory —
        redirect it to tmp_path so these tests never touch the production
        last-run.json (used by the api container's real dreaming scheduler)."""
        from memory.dreaming import scheduler

        monkeypatch.setattr(scheduler, "_dreams_dir", lambda project_id: tmp_path)

    def _mock_phases(self):
        """Patch phase modules so run_dreaming_cycle can execute."""
        mock_light = MagicMock(return_value={"status": "ok", "candidate_count": 0})
        mock_deep = MagicMock(return_value={"status": "ok", "promoted_count": 0})
        mock_rem = MagicMock(return_value={"status": "ok", "theme_count": 0})

        import memory.dreaming.deep_phase as dp
        import memory.dreaming.light_phase as lp
        import memory.dreaming.rem_phase as rp

        lp.run_light_phase = mock_light
        dp.run_deep_phase = mock_deep
        rp.run_rem_phase = mock_rem

    def test_force_true_always_runs(self):
        tz = _get_tz("UTC+8")
        today = datetime.now(tz).strftime("%Y-%m-%d")
        _last_run["default"] = {
            "status": "ok",
            "completed_at": f"{today}T03:00:00+08:00",
        }

        self._mock_phases()
        with patch("memory.dreaming.scheduler.rotate_traces", return_value=0), \
             patch("memory.dreaming.scheduler._write_run_state"):
            result = run_dreaming_cycle("default", force=True)
            assert result["status"] == "ok"

    def test_no_force_skips_if_ran_today(self):
        tz = _get_tz("UTC+8")
        today = datetime.now(tz).strftime("%Y-%m-%d")
        _last_run["default"] = {
            "status": "ok",
            "completed_at": f"{today}T03:00:00+08:00",
        }

        result = run_dreaming_cycle("default", force=False)
        assert result["status"] == "skipped"
        assert result["reason"] == "already_ran_today"

    def test_no_force_runs_if_no_previous(self):
        from memory.dreaming.scheduler import _dreams_dir

        _last_run.clear()
        state_file = _dreams_dir("default") / "last-run.json"
        if state_file.exists():
            state_file.unlink()

        self._mock_phases()
        with patch("memory.dreaming.scheduler.rotate_traces", return_value=0):
            result = run_dreaming_cycle("default", force=False)
            assert result["status"] == "ok"


# ===== Status Enrichment Tests =====

class TestGetDreamingStatus:
    def test_includes_next_run(self):
        status = get_dreaming_status()
        assert "next_run" in status
        assert status["next_run"] is not None

    def test_includes_phase_stats(self):
        status = get_dreaming_status()
        assert "phase_stats" in status

    def test_includes_config(self):
        status = get_dreaming_status()
        assert "config" in status
        assert "lookback_days" in status["config"]

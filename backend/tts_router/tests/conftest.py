"""Shared test fixtures and module stubs for tts_router tests."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Stub heavy external dependencies that are not installed in test env
# ---------------------------------------------------------------------------

sys.modules.setdefault("boto3", types.ModuleType("boto3"))
sys.modules.setdefault("edge_tts", types.ModuleType("edge_tts"))

_fake_tts_mod = types.ModuleType("google.cloud.texttospeech")
_fake_tts_mod.TextToSpeechClient = MagicMock  # type: ignore[attr-defined]
_fake_tts_mod.SynthesisInput = MagicMock  # type: ignore[attr-defined]
_fake_tts_mod.VoiceSelectionParams = MagicMock  # type: ignore[attr-defined]
_fake_tts_mod.AudioConfig = MagicMock  # type: ignore[attr-defined]
_fake_tts_mod.AudioEncoding = types.SimpleNamespace(LINEAR16="LINEAR16")  # type: ignore[attr-defined]
sys.modules.setdefault("google", types.ModuleType("google"))
sys.modules.setdefault("google.cloud", types.ModuleType("google.cloud"))
sys.modules.setdefault("google.cloud.texttospeech", _fake_tts_mod)

"""Shared test fixtures and module stubs for backend tests."""

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

# Stub markitdown (may not be installed in test env)
_fake_markitdown = types.ModuleType("markitdown")
_fake_markitdown.MarkItDown = MagicMock  # type: ignore[attr-defined]
sys.modules.setdefault("markitdown", _fake_markitdown)

# Stub openai (may not be installed in test env)
_fake_openai = types.ModuleType("openai")
_fake_openai.AsyncOpenAI = MagicMock  # type: ignore[attr-defined]
sys.modules.setdefault("openai", _fake_openai)

# Stub pytesseract (may not be installed in test env)
_fake_pytesseract = types.ModuleType("pytesseract")
_fake_pytesseract.image_to_string = MagicMock(return_value="")  # type: ignore[attr-defined]
sys.modules.setdefault("pytesseract", _fake_pytesseract)

# Stub PIL/Pillow (may not be installed in test env)
_fake_pil = types.ModuleType("PIL")
_fake_pil_image = types.ModuleType("PIL.Image")
_fake_pil_image.open = MagicMock()  # type: ignore[attr-defined]
_fake_pil.Image = _fake_pil_image  # type: ignore[attr-defined]
sys.modules.setdefault("PIL", _fake_pil)
sys.modules.setdefault("PIL.Image", _fake_pil_image)

# Note: yaml (pyyaml) is not stubbed — tests that need it should install it or mock locally

# Stub readability (may not be installed in test env)
_fake_readability = types.ModuleType("readability")
_fake_readability.Document = MagicMock  # type: ignore[attr-defined]
sys.modules.setdefault("readability", _fake_readability)

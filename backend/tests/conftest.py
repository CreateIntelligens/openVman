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

# Stub openai if not installed
try:
    import openai
except ImportError:
    _fake_openai = types.ModuleType("openai")
    _fake_openai.AsyncOpenAI = MagicMock  # type: ignore[attr-defined]
    _fake_openai.OpenAI = MagicMock  # type: ignore[attr-defined]
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

# Stub readability (may not be installed in test env)
_fake_readability = types.ModuleType("readability")
_fake_readability.Document = MagicMock  # type: ignore[attr-defined]
sys.modules.setdefault("readability", _fake_readability)


def _install_fake_prometheus_client() -> None:
    if "prometheus_client" in sys.modules:
        return

    module = types.ModuleType("prometheus_client")
    module.CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"
    _metrics: dict[str, "_FakeMetric"] = {}

    class CollectorRegistry:
        def __init__(self) -> None:
            self.metrics: dict[str, "_FakeMetric"] = {}

    class _FakeMetricChild:
        def __init__(self, metric: "_FakeMetric", labels: tuple[tuple[str, str], ...]) -> None:
            self._metric = metric
            self._labels = labels

        def inc(self, amount: float = 1.0) -> None:
            self._metric._values[self._labels] = self._metric._values.get(self._labels, 0.0) + amount

        def observe(self, value: float) -> None:
            key = ("sum",) + self._labels
            count_key = ("count",) + self._labels
            self._metric._values[key] = self._metric._values.get(key, 0.0) + value
            self._metric._values[count_key] = self._metric._values.get(count_key, 0.0) + 1.0

        def set(self, value: float) -> None:
            self._metric._values[self._labels] = value

    class _FakeMetric:
        def __init__(
            self,
            name: str,
            _doc: str,
            labelnames: list[str] | tuple[str, ...] | None = None,
            *,
            registry: CollectorRegistry | None = None,
            **_kwargs,
        ) -> None:
            self._name = name
            self._labelnames = tuple(labelnames or ())
            self._values: dict[tuple[tuple[str, str], ...] | tuple[object, ...], float] = {}
            if registry is None:
                _metrics[name] = self
            else:
                registry.metrics[name] = self

        def labels(self, *args, **kwargs) -> _FakeMetricChild:
            if kwargs:
                labels = tuple((name, str(kwargs[name])) for name in self._labelnames)
            else:
                labels = tuple((name, str(value)) for name, value in zip(self._labelnames, args, strict=False))
            return _FakeMetricChild(self, labels)

        def inc(self, amount: float = 1.0) -> None:
            self.labels().inc(amount)

        def observe(self, value: float) -> None:
            self.labels().observe(value)

        def set(self, value: float) -> None:
            self.labels().set(value)

    def _escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def _render_line(name: str, labels: tuple[tuple[str, str], ...], value: float) -> str:
        if not labels:
            return f"{name} {value}"
        rendered = ",".join(f'{key}="{_escape(val)}"' for key, val in labels)
        return f"{name}{{{rendered}}} {value}"

    def generate_latest(registry: CollectorRegistry | None = None) -> bytes:
        lines: list[str] = []
        metrics = registry.metrics if registry is not None else _metrics
        for name, metric in metrics.items():
            for labels, value in metric._values.items():
                if labels and labels[0] in {"sum", "count"}:
                    suffix, *rest = labels
                    lines.append(_render_line(f"{name}_{suffix}", tuple(rest), value))
                else:
                    lines.append(_render_line(name, labels, value))
        return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")

    module.CollectorRegistry = CollectorRegistry
    module.Counter = _FakeMetric
    module.Gauge = _FakeMetric
    module.Histogram = _FakeMetric
    module.generate_latest = generate_latest
    sys.modules["prometheus_client"] = module


_install_fake_prometheus_client()

# Note: yaml (pyyaml) is not stubbed — tests that need it should install it or mock locally

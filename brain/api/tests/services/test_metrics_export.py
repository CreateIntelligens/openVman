"""Tests for brain Prometheus export."""

from __future__ import annotations

import importlib
import sys
import types


def _install_fake_prometheus_client() -> None:
    if "prometheus_client" in sys.modules:
        return

    module = types.ModuleType("prometheus_client")
    module.CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

    class CollectorRegistry:
        def __init__(self) -> None:
            self.metrics: dict[str, "_FakeMetric"] = {}

    class _FakeMetricChild:
        def __init__(self, metric: "_FakeMetric", labels: tuple[tuple[str, str], ...]) -> None:
            self._metric = metric
            self._labels = labels

        def inc(self, amount: float = 1.0) -> None:
            self._metric._values[self._labels] = self._metric._values.get(self._labels, 0.0) + amount

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
            self._values: dict[tuple[tuple[str, str], ...], float] = {}
            if registry is not None:
                registry.metrics[name] = self

        def labels(self, **kwargs) -> _FakeMetricChild:
            labels = tuple((name, str(kwargs[name])) for name in self._labelnames)
            return _FakeMetricChild(self, labels)

        def inc(self, amount: float = 1.0) -> None:
            self.labels().inc(amount)

        def set(self, value: float) -> None:
            self.labels().set(value)

    def _escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def _render_line(name: str, labels: tuple[tuple[str, str], ...], value: float) -> str:
        if not labels:
            return f"{name} {value}"
        rendered = ",".join(
            f'{key}="{_escape(val)}"'
            for key, val in labels
        )
        return f"{name}{{{rendered}}} {value}"

    def generate_latest(registry: CollectorRegistry | None = None) -> bytes:
        lines: list[str] = []
        for metric in (registry.metrics.values() if registry is not None else []):
            for labels, value in metric._values.items():
                lines.append(_render_line(metric._name, labels, value))
        return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")

    module.CollectorRegistry = CollectorRegistry
    module.Counter = _FakeMetric
    module.Gauge = _FakeMetric
    module.generate_latest = generate_latest
    sys.modules["prometheus_client"] = module


_install_fake_prometheus_client()


def _fresh_observability():
    sys.modules.pop("safety.observability", None)
    obs = importlib.import_module("safety.observability")
    obs._metrics = None
    return obs


def test_prometheus_export_handles_special_label_values():
    obs = _fresh_observability()
    store = obs.get_metrics_store()

    store.increment(
        "tool_calls_total",
        tool_name='a/b,c=d "quoted"',
        status="ok",
    )

    payload = obs.render_prometheus(store).decode("utf-8")

    assert 'tool_name="a/b,c=d \\"quoted\\""' in payload
    assert 'status="ok"' in payload
    assert "tool_calls_total" in payload


def test_prometheus_export_renders_timing_series_names():
    obs = _fresh_observability()
    store = obs.get_metrics_store()

    store.observe("tool_latency_ms", 42.5, tool_name="search", status="ok")

    payload = obs.render_prometheus(store).decode("utf-8")

    assert "tool_latency_ms_count" in payload
    assert "tool_latency_ms_sum" in payload
    assert "tool_latency_ms_max" in payload

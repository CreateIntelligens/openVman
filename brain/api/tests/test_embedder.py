"""Tests for provider-aware embedding adapters."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def _load_embedder(monkeypatch, backend):
    fake_config_mod = types.ModuleType("config")
    fake_config_mod.get_settings = lambda: types.SimpleNamespace(
        resolve_embedding_backend=lambda version=None: backend,
    )
    monkeypatch.setitem(sys.modules, "config", fake_config_mod)

    fake_flag_mod = types.ModuleType("FlagEmbedding")

    class FakeBGEM3FlagModel:
        init_calls: list[tuple[str, bool, str]] = []

        def __init__(self, model_name, *, use_fp16, device):
            self.init_calls.append((model_name, use_fp16, device))

        def encode(self, texts):
            return {
                "dense_vecs": [
                    types.SimpleNamespace(tolist=lambda: [float(len(texts[0]))])
                    for _ in texts
                ]
            }

    fake_flag_mod.BGEM3FlagModel = FakeBGEM3FlagModel
    monkeypatch.setitem(sys.modules, "FlagEmbedding", fake_flag_mod)

    fake_openai_mod = types.ModuleType("openai")
    fake_openai_mod.OpenAI = object
    monkeypatch.setitem(sys.modules, "openai", fake_openai_mod)

    sys.modules.pop("memory.embedder", None)
    module = importlib.import_module("memory.embedder")
    return module, FakeBGEM3FlagModel


def test_bge_embedder_builds_local_model(monkeypatch):
    backend = types.SimpleNamespace(
        version="bge",
        provider="bge",
        model="BAAI/bge-m3",
        api_key="",
        base_url="",
        dimensions=None,
        use_fp16=False,
        device="cpu",
        multimodal=False,
    )

    module, fake_bge = _load_embedder(monkeypatch, backend)

    vectors = module.get_embedder().encode(["hello"])

    assert vectors == [[5.0]]
    assert fake_bge.init_calls == [("BAAI/bge-m3", False, "cpu")]


def test_openai_embedder_uses_embeddings_client(monkeypatch):
    backend = types.SimpleNamespace(
        version="openai",
        provider="openai",
        model="text-embedding-3-small",
        api_key="ok",
        base_url="",
        dimensions=256,
        use_fp16=False,
        device="cpu",
        multimodal=False,
    )

    module, _ = _load_embedder(monkeypatch, backend)
    captured: dict[str, object] = {}

    class FakeOpenAIClient:
        def __init__(self, *, api_key, base_url=None):
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            self.embeddings = self

        def create(self, **kwargs):
            captured["request"] = kwargs
            return types.SimpleNamespace(
                data=[types.SimpleNamespace(embedding=[0.1, 0.2])]
            )

    monkeypatch.setattr(module, "OpenAI", FakeOpenAIClient)

    vectors = module.get_embedder().encode(["hello"], input_type="query")

    assert vectors == [[0.1, 0.2]]
    assert captured["api_key"] == "ok"
    assert captured["request"] == {
        "model": "text-embedding-3-small",
        "input": ["hello"],
        "dimensions": 256,
    }


def test_gemini_embedder_uses_batch_embed_request(monkeypatch):
    backend = types.SimpleNamespace(
        version="gemini",
        provider="gemini",
        model="gemini-embedding-001",
        api_key="gk",
        base_url="",
        dimensions=128,
        use_fp16=False,
        device="cpu",
        multimodal=True,
    )

    module, _ = _load_embedder(monkeypatch, backend)
    captured: dict[str, object] = {}

    def fake_post_json(*, url, headers, payload):
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        return {"embeddings": [{"values": [0.3, 0.4]}]}

    monkeypatch.setattr(module, "_post_json", fake_post_json)

    vectors = module.get_embedder().encode(["hello"], input_type="query")

    assert vectors == [[0.3, 0.4]]
    assert str(captured["url"]).endswith(
        "/models/gemini-embedding-001:batchEmbedContents"
    )
    assert captured["payload"] == {
        "requests": [
            {
                "model": "models/gemini-embedding-001",
                "content": {"parts": [{"text": "hello"}]},
                "taskType": "RETRIEVAL_QUERY",
                "outputDimensionality": 128,
            }
        ]
    }


def test_voyage_embedder_uses_query_input_type(monkeypatch):
    backend = types.SimpleNamespace(
        version="voyage",
        provider="voyage",
        model="voyage-3-large",
        api_key="vk",
        base_url="",
        dimensions=512,
        use_fp16=False,
        device="cpu",
        multimodal=True,
    )

    module, _ = _load_embedder(monkeypatch, backend)
    captured: dict[str, object] = {}

    def fake_post_json(*, url, headers, payload):
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        return {"data": [{"embedding": [0.5, 0.6]}]}

    monkeypatch.setattr(module, "_post_json", fake_post_json)

    vectors = module.get_embedder().encode(["hello"], input_type="query")

    assert vectors == [[0.5, 0.6]]
    assert captured["url"] == "https://api.voyageai.com/v1/embeddings"
    assert captured["payload"] == {
        "input": ["hello"],
        "model": "voyage-3-large",
        "input_type": "query",
        "output_dimension": 512,
    }

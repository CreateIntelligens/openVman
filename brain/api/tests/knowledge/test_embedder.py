"""Tests for provider-aware embedding adapters."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def _load_embedder(monkeypatch, backend, *, settings=None):
    fake_settings = settings or types.SimpleNamespace(
        resolved_embedding_active_version=backend.version,
        resolved_embedding_version_order=[backend.version],
        resolve_embedding_backend=lambda version=None: backend,
    )
    fake_config_mod = types.ModuleType("config")
    fake_config_mod.get_settings = lambda: fake_settings
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


def test_encode_query_with_fallback_uses_next_version_after_error(monkeypatch):
    backends = {
        "bge": types.SimpleNamespace(
            version="bge",
            provider="bge",
            model="BAAI/bge-m3",
            api_key="",
            base_url="",
            dimensions=None,
            use_fp16=False,
            device="cpu",
            multimodal=False,
        ),
        "gemini": types.SimpleNamespace(
            version="gemini",
            provider="gemini",
            model="gemini-embedding-001",
            api_key="gk",
            base_url="",
            dimensions=128,
            use_fp16=False,
            device="api",
            multimodal=False,
        ),
    }
    settings = types.SimpleNamespace(
        resolved_embedding_active_version="bge",
        resolved_embedding_version_order=["bge", "gemini"],
        resolve_embedding_backend=lambda version=None: backends[(version or "bge")],
    )

    module, _ = _load_embedder(monkeypatch, backends["bge"], settings=settings)
    fake_db_mod = types.ModuleType("infra.db")
    fake_db_mod.vector_table_exists = (
        lambda table_name, project_id="default", embedding_version=None: embedding_version == "gemini"
    )
    monkeypatch.setitem(sys.modules, "infra.db", fake_db_mod)

    def fake_get_embedder(version=None):
        if version == "bge":
            raise RuntimeError("bge unavailable")
        return types.SimpleNamespace(
            encode=lambda texts, input_type="document": [[0.9, 0.8]]
        )

    monkeypatch.setattr(module, "get_embedder", fake_get_embedder)

    route = module.encode_query_with_fallback(
        "hello",
        project_id="proj-1",
        table_names=("knowledge",),
    )

    assert route.version == "gemini"
    assert route.vector == [0.9, 0.8]
    assert route.attempted_versions == [
        {"version": "bge", "status": "error", "reason": "RuntimeError"},
        {"version": "gemini", "status": "selected"},
    ]


def test_encode_query_with_fallback_skips_versions_without_tables(monkeypatch):
    backends = {
        "bge": types.SimpleNamespace(
            version="bge",
            provider="bge",
            model="BAAI/bge-m3",
            api_key="",
            base_url="",
            dimensions=None,
            use_fp16=False,
            device="cpu",
            multimodal=False,
        ),
        "gemini": types.SimpleNamespace(
            version="gemini",
            provider="gemini",
            model="gemini-embedding-001",
            api_key="gk",
            base_url="",
            dimensions=128,
            use_fp16=False,
            device="api",
            multimodal=False,
        ),
        "openai": types.SimpleNamespace(
            version="openai",
            provider="openai",
            model="text-embedding-3-small",
            api_key="ok",
            base_url="",
            dimensions=256,
            use_fp16=False,
            device="api",
            multimodal=False,
        ),
    }
    settings = types.SimpleNamespace(
        resolved_embedding_active_version="bge",
        resolved_embedding_version_order=["bge", "gemini", "openai"],
        resolve_embedding_backend=lambda version=None: backends[(version or "bge")],
    )

    module, _ = _load_embedder(monkeypatch, backends["bge"], settings=settings)
    fake_db_mod = types.ModuleType("infra.db")
    fake_db_mod.vector_table_exists = (
        lambda table_name, project_id="default", embedding_version=None: embedding_version == "openai"
    )
    monkeypatch.setitem(sys.modules, "infra.db", fake_db_mod)

    def fake_get_embedder(version=None):
        if version == "bge":
            raise RuntimeError("bge unavailable")
        return types.SimpleNamespace(
            encode=lambda texts, input_type="document": [[1.1, 1.2]]
        )

    monkeypatch.setattr(module, "get_embedder", fake_get_embedder)

    route = module.encode_query_with_fallback(
        "hello",
        project_id="proj-1",
        table_names=("knowledge",),
    )

    assert route.version == "openai"
    assert route.attempted_versions == [
        {"version": "bge", "status": "error", "reason": "RuntimeError"},
        {"version": "gemini", "status": "skipped", "reason": "missing_tables"},
        {"version": "openai", "status": "selected"},
    ]

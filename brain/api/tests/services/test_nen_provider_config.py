"""NEN provider configuration and fallback routing tests."""

import importlib

from config import BrainSettings


def test_nen_and_openai_resolve_independently() -> None:
    settings = BrainSettings(
        _env_file=None,
        llm_provider="gemini",
        gemini_api_key="gemini-key",
        nen_api_key="nen-key",
        nen_base_url="https://nen.example/v1",
        openai_api_key="openai-key",
    )

    assert settings.resolve_api_key_for_provider("nen") == "nen-key"
    assert settings.resolve_base_url_for_provider("nen") == "https://nen.example/v1"
    assert settings.resolve_api_key_for_provider("openai") == "openai-key"
    assert settings.resolve_base_url_for_provider("openai") == ""


def test_nen_uses_its_default_endpoint() -> None:
    settings = BrainSettings(_env_file=None, nen_api_key="nen-key")

    assert settings.resolve_base_url_for_provider("nen") == "https://nen.com.tw/v1"


def test_nen_usage_preserves_provider_identity(monkeypatch) -> None:
    llm_client = importlib.import_module("core.llm_client")
    recorded: list[dict] = []
    monkeypatch.setattr(
        llm_client,
        "record_usage_event",
        lambda **kwargs: recorded.append(kwargs),
    )

    llm_client._record_llm_usage("nen", "nen-model", None, 12.5)

    assert recorded[0]["provider"] == "nen"
    assert recorded[0]["model"] == "nen-model"


def test_nen_remains_last_in_explicit_fallback_chain(monkeypatch) -> None:
    fallback_chain = importlib.import_module("core.fallback_chain")
    settings = BrainSettings(
        _env_file=None,
        llm_provider="gemini",
        llm_model="gemini-primary",
        llm_fallback_chain=(
            "gemini:gemini-primary,groq:groq-fallback,nen:nen-fallback"
        ),
        llm_disable_model_discovery=True,
        gemini_api_key="gemini-key",
        groq_api_key="groq-key",
        nen_api_key="nen-key",
    )
    monkeypatch.setattr(fallback_chain, "get_settings", lambda: settings)

    hops = fallback_chain.build_fallback_chain("nen-order")

    assert [(hop.provider, hop.model) for hop in hops] == [
        ("gemini", "gemini-primary"),
        ("groq", "groq-fallback"),
        ("nen", "nen-fallback"),
    ]
    assert hops[-1].api_key == "nen-key"
    assert hops[-1].base_url == "https://nen.com.tw/v1"

"""Which model providers each category can use, and their deployment defaults.

A category is one job a model does for the whole site (typed decisions, the
main conversation). Each category lists the hops the Admin may reorder or
disable. Credentials belong to vendors, not hops, so one OpenAI key serves
both categories and a Clef key serves both Clef endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from app.config import TTSRouterConfig


@dataclass(frozen=True, slots=True)
class Credential:
    id: str
    label: str
    environment_variable: str


@dataclass(frozen=True, slots=True)
class ProviderHop:
    id: str
    credential_id: str
    label: str
    endpoint: str
    model: str
    credential_required: bool


@dataclass(frozen=True, slots=True)
class ModelCategory:
    id: str
    label: str
    hops: tuple[ProviderHop, ...]
    # 決策的模型名稱跟端點綁在一起（各家各自只有一個決策模型），主對話則要能換模型。
    model_editable: bool

    @property
    def hop_ids(self) -> tuple[str, ...]:
        return tuple(hop.id for hop in self.hops)

    def hop(self, hop_id: str) -> ProviderHop:
        for hop in self.hops:
            if hop.id == hop_id:
                return hop
        raise KeyError(hop_id)


CREDENTIALS: Final[tuple[Credential, ...]] = (
    Credential("clef", "Clef", "CLEF_API_KEY"),
    Credential("jev", "Jev", "TYPESAFE_API_KEY"),
    Credential("openai", "OpenAI", "OPENAI_API_KEY"),
    Credential("gemini", "Gemini", "GEMINI_API_KEY"),
    Credential("groq", "Groq", "GROQ_API_KEY"),
    Credential("nen", "NEN", "NEN_API_KEY"),
)
CREDENTIAL_IDS: Final[frozenset[str]] = frozenset(item.id for item in CREDENTIALS)

DECISION: Final = ModelCategory(
    id="decision",
    label="決策模型",
    model_editable=False,
    hops=(
        ProviderHop(
            "clef-primary", "clef", "Clef 主端點",
            "https://clef.create360.ai/v1/systemone", "clef-flash", False,
        ),
        ProviderHop(
            "clef-backup", "clef", "Clef 備援端點",
            "https://clef.aiurl.tw/v1/systemone", "clef-flash", False,
        ),
        ProviderHop(
            "jev", "jev", "Jev",
            "https://api.typesafe.ai/v1/systemone", "jev-latest", True,
        ),
        ProviderHop(
            "openai", "openai", "OpenAI Decisions",
            "https://api.openai.com/v1/decisions", "gpt-6-luna", True,
        ),
    ),
)

CHAT_LLM: Final = ModelCategory(
    id="chat_llm",
    label="主對話模型",
    model_editable=True,
    hops=(
        ProviderHop(
            "gemini", "gemini", "Gemini",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
            "gemini-3.5-flash-lite", True,
        ),
        ProviderHop(
            "openai", "openai", "OpenAI",
            "https://api.openai.com/v1", "gpt-4.1-mini", True,
        ),
        ProviderHop(
            "groq", "groq", "Groq",
            "https://api.groq.com/openai/v1", "openai/gpt-oss-120b", True,
        ),
        # NEN 的網址由部署設定（NEN_BASE_URL），這裡只是沒設定時顯示用的預設。
        ProviderHop(
            "nen", "nen", "NEN",
            "https://nen.com.tw/v1", "gemini-3.5-flash-lite", True,
        ),
    ),
)

CATEGORIES: Final[dict[str, ModelCategory]] = {
    category.id: category for category in (DECISION, CHAT_LLM)
}


@dataclass(frozen=True, slots=True)
class CategoryDefaults:
    order: tuple[str, ...]
    enabled: tuple[str, ...]
    models: dict[str, str]


def environment_credential(config: TTSRouterConfig, credential_id: str) -> str:
    values = {
        "clef": config.clef_api_key,
        "jev": config.typesafe_api_key,
        "openai": config.openai_api_key,
        "gemini": config.gemini_api_key,
        "groq": config.groq_api_key,
        "nen": config.nen_api_key,
    }
    return values[credential_id]


def hop_endpoint(config: TTSRouterConfig, category: ModelCategory, hop: ProviderHop) -> str:
    if category is DECISION and hop.id == "jev":
        base = config.jev_base_url.strip().rstrip("/") or "https://api.typesafe.ai"
        return base if base.endswith("/v1/systemone") else f"{base}/v1/systemone"
    if category is CHAT_LLM and hop.id == "nen":
        return config.nen_base_url.strip() or hop.endpoint
    return hop.endpoint


def category_defaults(config: TTSRouterConfig, category: ModelCategory) -> CategoryDefaults:
    """What the category does before anyone saves settings in the Admin."""
    if category is not CHAT_LLM:
        return CategoryDefaults(category.hop_ids, category.hop_ids, {})
    chain = _parse_llm_chain(config)
    models: dict[str, str] = {}
    for provider, model in chain:
        if provider in category.hop_ids:
            models.setdefault(provider, model)
    configured = tuple(models)
    order = configured + tuple(hop_id for hop_id in category.hop_ids if hop_id not in models)
    for hop in category.hops:
        models.setdefault(hop.id, hop.model)
    return CategoryDefaults(order, configured, models)


def _parse_llm_chain(config: TTSRouterConfig) -> list[tuple[str, str]]:
    # 跟 Brain 的 LLM_FALLBACK_CHAIN 解析規則一致：沒設定鏈時就是 LLM_PROVIDER 單一家。
    pairs: list[tuple[str, str]] = []
    for entry in config.llm_fallback_chain.split(","):
        provider, _, model = entry.partition(":")
        if provider.strip() and model.strip():
            pairs.append((provider.strip(), model.strip()))
    return pairs or [(config.llm_provider.strip(), config.llm_model.strip())]


__all__ = [
    "CATEGORIES",
    "CHAT_LLM",
    "CREDENTIALS",
    "CREDENTIAL_IDS",
    "CategoryDefaults",
    "Credential",
    "DECISION",
    "ModelCategory",
    "ProviderHop",
    "category_defaults",
    "environment_credential",
    "hop_endpoint",
]

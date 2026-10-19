"""Project-scoped model settings and Gemini credentials from Backend.

An absent project keeps the deployment's legacy shared behavior. Once a
project is selected, only Backend may decide whether it uses a shared key.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, fields
from functools import wraps
from inspect import signature
from threading import Lock
from typing import Any

import httpx

import config
from core.model_provider_config import (
    ModelProviderConfigUnavailable,
    RefreshingValue,
    fetch_document,
    fetch_section,
)
from core.usage import current_usage_scope, usage_scope

_PROJECT: ContextVar[str | None] = ContextVar("model_project", default=None)
_DOCUMENTS: OrderedDict[str, RefreshingValue[dict[str, Any]]] = OrderedDict()
_DOCUMENTS_LOCK = Lock()
_SHARED: RefreshingValue[GeminiCredential] = RefreshingValue()


class GeminiCredentialUnavailable(ModelProviderConfigUnavailable):
    """The selected project's credential could not be resolved safely."""


@dataclass(frozen=True, slots=True)
class GeminiCredential:
    api_key: str = field(repr=False)
    source: str = "shared"
    credential_id: str = "gemini"
    configured: bool = False

    def metadata(self) -> dict[str, str]:
        return {
            "credential_source": self.source,
            "credential_id": self.credential_id,
        }


def current_model_project(project_id: str | None = None) -> str | None:
    if project_id is not None:
        return project_id or "default"
    explicit = _PROJECT.get()
    if explicit is not None:
        return explicit
    scope = current_usage_scope()
    return scope.project_id if scope is not None else None


@contextmanager
def project_model_scope(project_id: str, *, kind: str = "internal") -> Iterator[None]:
    project_id = project_id or "default"
    token = _PROJECT.set(project_id)
    try:
        scope = current_usage_scope()
        if scope is None or scope.project_id != project_id:
            attribution = (
                {item.name: getattr(scope, item.name) for item in fields(scope)}
                if scope is not None else {"kind": kind}
            )
            with usage_scope(**{**attribution, "project_id": project_id}):
                yield
        else:
            yield
    finally:
        _PROJECT.reset(token)


def project_model_entry(kind: str) -> Callable:
    """Bind a synchronous entry point's explicit project before nested LLM calls."""
    def decorate(function: Callable) -> Callable:
        parameters = signature(function)

        @wraps(function)
        def scoped(*args: Any, **kwargs: Any) -> Any:
            bound = parameters.bind(*args, **kwargs)
            bound.apply_defaults()
            with project_model_scope(bound.arguments["project_id"], kind=kind):
                return function(*args, **kwargs)

        return scoped
    return decorate


def _parse_credential(raw: Any) -> GeminiCredential:
    if (
        not isinstance(raw, dict)
        or not isinstance(raw.get("api_key"), str)
        or raw.get("source") not in {"project", "shared"}
        or not isinstance(raw.get("credential_id"), str)
        or not isinstance(raw.get("configured"), bool)
    ):
        raise GeminiCredentialUnavailable("invalid Gemini credential document")
    return GeminiCredential(
        raw["api_key"], raw["source"], raw["credential_id"], raw["configured"],
    )


def _fetch_project_document(project_id: str) -> dict[str, Any]:
    try:
        document = fetch_document(timeout=1.0, params={"project_id": project_id})
    except httpx.HTTPStatusError as exc:
        # A broken binding is authoritative, unlike a temporary network outage.
        # In particular an older shared answer must not bypass a new binding.
        try:
            detail = exc.response.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        if (
            detail == "project_gemini_credential_unavailable"
            or 400 <= exc.response.status_code < 500
        ):
            raise GeminiCredentialUnavailable("project Gemini credential unavailable") from None
        raise
    _parse_credential(document.get("gemini_credential"))
    if not isinstance(document.get("chat_llm"), dict):
        raise GeminiCredentialUnavailable("project chat configuration unavailable")
    return document


def project_provider_document(project_id: str) -> dict[str, Any]:
    with _DOCUMENTS_LOCK:
        cached = _DOCUMENTS.setdefault(project_id, RefreshingValue())
        _DOCUMENTS.move_to_end(project_id)
        if len(_DOCUMENTS) > 256:
            _DOCUMENTS.popitem(last=False)
    try:
        return cached.get(
            lambda: _fetch_project_document(project_id),
            propagate=(GeminiCredentialUnavailable,),
        )
    except GeminiCredentialUnavailable:
        cached.clear()
        raise


def resolve_gemini_credential(project_id: str | None = None) -> GeminiCredential:
    selected = current_model_project(project_id)
    if selected is not None:
        credential = _parse_credential(
            project_provider_document(selected)["gemini_credential"],
        )
    else:
        def load() -> GeminiCredential:
            return _parse_credential(fetch_section("gemini_credential", timeout=1.0))
        credential = _SHARED.get(load, default=GeminiCredential(""))
    # Unbound deployments may keep their Gemini key only in Brain's env.
    # Explicitly cleared shared credentials and project credentials never do.
    if credential.source == "shared" and not credential.configured and not credential.api_key:
        cfg = config.get_settings()
        resolver = getattr(cfg, "resolve_api_key_for_provider", None)
        key = resolver("gemini") if resolver else cfg.gemini_api_key
        return GeminiCredential(key, "shared", credential.credential_id, bool(key))
    return credential


def clear_project_provider_cache() -> None:
    with _DOCUMENTS_LOCK:
        for cached in _DOCUMENTS.values():
            cached.clear()
        _DOCUMENTS.clear()
    _SHARED.clear()

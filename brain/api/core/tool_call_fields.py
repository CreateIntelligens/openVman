"""Normalize fields of tool calls returned by OpenAI-compatible providers."""

from __future__ import annotations

from typing import Any


def normalize_tool_arguments(raw: str | None) -> str:
    """Gemini 的 OpenAI 相容端點拒收歷史裡 arguments 為空字串的 tool call（400
    INVALID_ARGUMENT），而模型偶爾會吐出不帶參數的呼叫；這筆一旦寫回對話歷史，
    下一輪整個請求就失敗。統一成 "{}"，參數缺漏交給工具的 schema 驗證回報。"""
    return raw if raw and raw.strip() else "{}"


def extract_thought_signature(obj: Any) -> str | None:
    """Extract Google thought_signature from a tool call or delta object."""
    if not obj:
        return None
    if isinstance(obj, dict):
        if sig := obj.get("thought_signature") or obj.get("thought"):
            return str(sig)
        if google := obj.get("google"):
            if isinstance(google, dict) and (sig := google.get("thought_signature")):
                return str(sig)
        if extra := obj.get("extra_content"):
            return extract_thought_signature(extra)
        return None

    if hasattr(obj, "thought_signature") and (sig := getattr(obj, "thought_signature", None)):
        return str(sig)

    for attr in ("extra_content", "model_extra"):
        val = getattr(obj, attr, None)
        if val and (sig := extract_thought_signature(val)):
            return sig

    if hasattr(obj, "function"):
        fn = getattr(obj, "function", None)
        if fn and (sig := extract_thought_signature(fn)):
            return sig

    return None


def tool_call_extra_content(tool_call: Any) -> dict[str, Any] | None:
    if sig := extract_thought_signature(tool_call):
        return {"thought_signature": sig}
    return None

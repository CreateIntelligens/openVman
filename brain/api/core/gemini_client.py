"""One google-genai client per API key, shared by every turn in the process."""

from __future__ import annotations

from collections import OrderedDict
from threading import Lock
from typing import Any

_CACHE_MAX = 32
_clients: "OrderedDict[str, Any]" = OrderedDict()
_lock = Lock()


def gemini_client_for_key(api_key: str) -> Any | None:
    """Return the cached client for *api_key*, building it on first use; None if the SDK fails."""
    # 每題都會走到這裡；genai.Client 建構時要載入 CA 憑證建兩個 SSL context，
    # 同時 100 題時光這一步就佔掉 Brain 約兩成 CPU，所以同一把金鑰共用一個。
    with _lock:
        client = _clients.get(api_key)
        if client is not None:
            _clients.move_to_end(api_key)
            return client
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
        except Exception:
            return None
        _clients[api_key] = client
        if len(_clients) > _CACHE_MAX:
            _clients.popitem(last=False)
        return client


def clear_gemini_clients() -> None:
    with _lock:
        _clients.clear()

"""Provider-safe tool names for OpenAI-compatible chat requests.

Skill tools are named ``skill:tool`` and project-scoped ones ``proj:<id>:skill:tool``.
OpenAI rejects any function name outside ``^[a-zA-Z0-9_-]{1,64}$`` with HTTP 400,
both in ``tools`` and in the conversation history (assistant ``tool_calls`` and
``role=tool`` messages). Names are rewritten for one request only and mapped back
when the reply comes in, so the rest of Brain keeps using the original names.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from typing import Any, Iterable

_MAX_LEN = 64
_VALID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_INVALID_CHAR = re.compile(r"[^A-Za-z0-9_-]")


def is_valid_tool_name(name: str) -> bool:
    return bool(_VALID.match(name))


def _sanitize(name: str) -> str:
    # 冒號是命名空間分隔，換成雙底線讀起來仍看得出層級；其他字元換單底線。
    wire = _INVALID_CHAR.sub(lambda m: "__" if m.group() == ":" else "_", name) or "tool"
    if len(wire) > _MAX_LEN:
        digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
        wire = f"{wire[:_MAX_LEN - 9]}_{digest}"
    return wire


class ToolNameCodec:
    """Two-way map between Brain tool names and the names sent on the wire.

    Valid names are registered first and keep their spelling; an encoded name that
    would collide with one of them gets a numeric suffix. Decoding only looks up
    names this codec produced, so a valid name that happens to contain ``__`` is
    never turned back into a colon.
    """

    def __init__(self, names: Iterable[str]) -> None:
        self._to_wire: dict[str, str] = {}
        self._from_wire: dict[str, str] = {}
        unique = list(dict.fromkeys(n for n in names if isinstance(n, str) and n))
        for name in [n for n in unique if is_valid_tool_name(n)]:
            self._register(name, name)
        for name in [n for n in unique if not is_valid_tool_name(n)]:
            self._register(name, _sanitize(name))

    def _register(self, name: str, candidate: str) -> None:
        wire = candidate
        suffix = 2
        while wire in self._from_wire:
            tail = f"_{suffix}"
            wire = f"{candidate[:_MAX_LEN - len(tail)]}{tail}"
            suffix += 1
        self._to_wire[name] = wire
        self._from_wire[wire] = name

    @property
    def rewrites(self) -> bool:
        return any(name != wire for name, wire in self._to_wire.items())

    def encode(self, name: str) -> str:
        return self._to_wire.get(name, name)

    def decode(self, wire: str) -> str:
        return self._from_wire.get(wire, wire)


@dataclass(frozen=True, slots=True)
class EncodedRequest:
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None
    forced_tool_name: str | None
    codec: ToolNameCodec


def _tool_def_name(tool: Any) -> str | None:
    if isinstance(tool, dict):
        function = tool.get("function")
        if isinstance(function, dict):
            name = function.get("name")
            return name if isinstance(name, str) else None
    return None


def _history_names(messages: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("role") == "tool" and isinstance(message.get("name"), str):
            names.append(message["name"])
        for call in message.get("tool_calls") or ():
            function = call.get("function") if isinstance(call, dict) else None
            if isinstance(function, dict) and isinstance(function.get("name"), str):
                names.append(function["name"])
    return names


def _encode_message(message: Any, codec: ToolNameCodec) -> Any:
    if not isinstance(message, dict):
        return message
    out = message
    if message.get("role") == "tool" and isinstance(message.get("name"), str):
        out = {**out, "name": codec.encode(message["name"])}
    calls = message.get("tool_calls")
    if calls:
        new_calls = []
        for call in calls:
            function = call.get("function") if isinstance(call, dict) else None
            if isinstance(function, dict) and isinstance(function.get("name"), str):
                call = {**call, "function": {**function, "name": codec.encode(function["name"])}}
            new_calls.append(call)
        out = {**out, "tool_calls": new_calls}
    return out


def encode_tool_names(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    forced_tool_name: str | None,
    *,
    passthrough: frozenset[str] = frozenset(),
) -> EncodedRequest:
    """Return copies of *messages*/*tools* with provider-safe names; inputs are untouched.

    *passthrough* holds sentinel values of ``forced_tool_name`` that are not names.
    """
    names = [n for n in (_tool_def_name(t) for t in tools or ()) if n]
    names += _history_names(messages)
    if forced_tool_name and forced_tool_name not in passthrough:
        names.append(forced_tool_name)
    codec = ToolNameCodec(names)
    if not codec.rewrites:
        return EncodedRequest(messages, tools, forced_tool_name, codec)

    encoded_tools = None
    if tools is not None:
        encoded_tools = []
        for tool in tools:
            name = _tool_def_name(tool)
            if name is not None:
                tool = {**tool, "function": {**tool["function"], "name": codec.encode(name)}}
            encoded_tools.append(tool)
    forced = (
        forced_tool_name
        if not forced_tool_name or forced_tool_name in passthrough
        else codec.encode(forced_tool_name)
    )
    return EncodedRequest(
        [_encode_message(m, codec) for m in messages], encoded_tools, forced, codec,
    )


def decode_reply(reply: Any, codec: ToolNameCodec) -> Any:
    """Map tool-call names in an ``LLMReply`` back to Brain's names."""
    if not reply.tool_calls or not codec.rewrites:
        return reply
    return replace(
        reply,
        tool_calls=[replace(call, name=codec.decode(call.name)) for call in reply.tool_calls],
    )


__all__ = [
    "EncodedRequest",
    "ToolNameCodec",
    "decode_reply",
    "encode_tool_names",
    "is_valid_tool_name",
]

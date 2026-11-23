"""Provider-safe tool names: encode for the wire, decode replies back."""

from __future__ import annotations

import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from core.tool_names import ToolNameCodec, encode_tool_names, is_valid_tool_name  # noqa: E402


def _tool(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "parameters": {"type": "object"}}}


def test_colon_names_become_valid_and_round_trip():
    names = [
        "weather:get_current_weather",
        "a2a:a2a_send_task",
        "proj:proj-b85afb8bb6:graphify:run",
        "knowledge_search",
    ]
    codec = ToolNameCodec(names)
    for name in names:
        wire = codec.encode(name)
        assert is_valid_tool_name(wire)
        assert codec.decode(wire) == name
    assert codec.encode("weather:get_current_weather") == "weather__get_current_weather"
    assert codec.encode("knowledge_search") == "knowledge_search"


def test_valid_name_with_double_underscore_is_not_decoded_into_a_colon():
    codec = ToolNameCodec(["my__tool", "other:tool"])
    assert codec.decode("my__tool") == "my__tool"
    assert codec.decode("unknown__name") == "unknown__name"


def test_encoded_name_colliding_with_a_real_one_gets_a_suffix():
    codec = ToolNameCodec(["joke:get_joke", "joke__get_joke"])
    assert codec.encode("joke__get_joke") == "joke__get_joke"
    wire = codec.encode("joke:get_joke")
    assert wire != "joke__get_joke" and is_valid_tool_name(wire)
    assert codec.decode(wire) == "joke:get_joke"


def test_long_names_are_cut_to_the_provider_limit_and_stay_distinct():
    a = "proj:" + "x" * 70 + ":skill:a"
    b = "proj:" + "x" * 70 + ":skill:b"
    codec = ToolNameCodec([a, b])
    assert len(codec.encode(a)) <= 64 and len(codec.encode(b)) <= 64
    assert codec.encode(a) != codec.encode(b)
    assert codec.decode(codec.encode(b)) == b


def test_request_is_rewritten_everywhere_without_touching_the_input():
    tools = [_tool("weather:get_current_weather"), _tool("knowledge_search")]
    messages = [
        {"role": "user", "content": "天氣"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "c1",
                "type": "function",
                "function": {"name": "joke:get_joke", "arguments": "{}"},
            }],
        },
        {"role": "tool", "tool_call_id": "c1", "name": "joke:get_joke", "content": "哈"},
    ]
    request = encode_tool_names(messages, tools, "weather:get_current_weather")

    assert [t["function"]["name"] for t in request.tools] == [
        "weather__get_current_weather", "knowledge_search",
    ]
    assert request.messages[1]["tool_calls"][0]["function"]["name"] == "joke__get_joke"
    assert request.messages[2]["name"] == "joke__get_joke"
    assert request.forced_tool_name == "weather__get_current_weather"
    # 呼叫端的 list 是 agent loop 的工作歷史，不能被改到。
    assert tools[0]["function"]["name"] == "weather:get_current_weather"
    assert messages[1]["tool_calls"][0]["function"]["name"] == "joke:get_joke"
    assert messages[2]["name"] == "joke:get_joke"


def test_valid_request_is_passed_through_unchanged():
    tools = [_tool("knowledge_search")]
    messages = [{"role": "user", "content": "hi"}]
    request = encode_tool_names(messages, tools, "*", passthrough=frozenset({"*"}))
    assert request.tools is tools and request.messages is messages
    assert request.forced_tool_name == "*"
    assert not request.codec.rewrites

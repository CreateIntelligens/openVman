"""Sentence streaming for /brain/chat/stream: splitter, sink and the LLM plumbing.

整合方要拿第一句先送 TTS；句子切錯（把 3.5、網址、型號切開）會直接念錯，
工具輪的文字漏出去則會念出不屬於答案的話。
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from core.reply_stream import ReplyStream, SentenceSplitter, split_sentences


def _streamed(text: str, step: int = 1) -> list[str]:
    splitter = SentenceSplitter()
    sentences: list[str] = []
    for start in range(0, len(text), step):
        sentences += splitter.feed(text[start:start + step])
    return sentences + splitter.flush()


# ---------------------------------------------------------------------------
# SentenceSplitter
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(
            "營業時間是早上九點。週末休息！要預約嗎？",
            ["營業時間是早上九點。", "週末休息！", "要預約嗎？"],
            id="chinese",
        ),
        pytest.param(
            "分店有三間；台北兩間…高雄一間",
            ["分店有三間；", "台北兩間…", "高雄一間"],
            id="semicolon-and-ellipsis",
        ),
        pytest.param(
            "今日は晴れです。明日は雨？",
            ["今日は晴れです。", "明日は雨？"],
            id="japanese",
        ),
        pytest.param(
            "We open at nine. Weekends are closed! Need a booking?",
            ["We open at nine.", " Weekends are closed!", " Need a booking?"],
            id="english",
        ),
        pytest.param(
            "HIPPO-50 支援 HDMI. 另外 HIPPO-60 也有。真的嗎?我確認一下",
            ["HIPPO-50 支援 HDMI.", " 另外 HIPPO-60 也有。", "真的嗎?", "我確認一下"],
            id="mixed",
        ),
        pytest.param(
            "價格是 3.5 萬元，版本 v2.0.1 可用。",
            ["價格是 3.5 萬元，版本 v2.0.1 可用。"],
            id="decimals-and-versions",
        ),
        pytest.param(
            "型號 HIPPO-50 與 EV-3.5K 都有貨。",
            ["型號 HIPPO-50 與 EV-3.5K 都有貨。"],
            id="model-numbers",
        ),
        pytest.param(
            "請看 https://evak.com.tw/p/HIPPO-50.html?id=3.5&q=a!b 的說明。See www.example.com/a.b for more.",
            [
                "請看 https://evak.com.tw/p/HIPPO-50.html?id=3.5&q=a!b 的說明。",
                "See www.example.com/a.b for more.",
            ],
            id="urls",
        ),
        pytest.param(
            "他說：「好。」然後走了…… 是嗎",
            ["他說：「好。」", "然後走了……", " 是嗎"],
            id="closing-quotes",
        ),
        pytest.param(
            "**注意：營業時間會變動。**下一句",
            ["**注意：營業時間會變動。**", "下一句"],
            id="markdown-emphasis",
        ),
        pytest.param(
            "步驟如下\n1. 開機\n2. 登入\n\n完成",
            ["步驟如下", "\n1. 開機", "\n2. 登入", "\n\n完成"],
            id="newlines-and-list-markers",
        ),
        pytest.param(
            "Mr. Smith said e.g. this. Wait... what",
            ["Mr. Smith said e.g. this.", " Wait...", " what"],
            id="abbreviations-and-dots",
        ),
        pytest.param(
            "  \n 還沒說完的最後一段  \n\n",
            ["還沒說完的最後一段"],
            id="trailing-remainder",
        ),
    ],
)
def test_split_sentences(text: str, expected: list[str]) -> None:
    assert split_sentences(text) == expected
    assert "".join(expected) == text.strip()


@pytest.mark.parametrize("step", [1, 2, 3, 7])
def test_streamed_deltas_split_like_the_whole_text(step: int) -> None:
    text = (
        "HIPPO-50 售價 3.5 萬。詳見 https://evak.com.tw/a.b?c=1. \n"
        "Need help? 歡迎來電！最後一句"
    )
    assert _streamed(text, step) == split_sentences(text)
    assert "".join(_streamed(text, step)) == text.strip()


def test_decimal_split_across_deltas_is_not_a_boundary() -> None:
    splitter = SentenceSplitter()
    assert splitter.feed("價格 3.") == []
    assert splitter.feed("5 萬。") == []  # 等下一個字確認句尾沒有收尾引號
    assert splitter.feed("好") == ["價格 3.5 萬。"]
    assert splitter.flush() == ["好"]


def test_first_sentence_is_available_before_the_text_ends() -> None:
    splitter = SentenceSplitter()
    assert splitter.feed("第一句。第") == ["第一句。"]


# ---------------------------------------------------------------------------
# ReplyStream
# ---------------------------------------------------------------------------

def _sink() -> tuple[ReplyStream, list[tuple[int, str]]]:
    sent: list[tuple[int, str]] = []
    return ReplyStream(lambda index, text: sent.append((index, text))), sent


def test_sentences_stream_then_finish_sends_the_rest() -> None:
    stream, sent = _sink()
    stream.attempt_started()
    for piece in ["  營業", "時間九點。週", "末休息"]:
        stream.text_delta(piece)

    assert sent == [(0, "營業時間九點。")]

    stream.finish("營業時間九點。週末休息")
    assert sent == [(0, "營業時間九點。"), (1, "週末休息")]


def test_unstreamed_reply_is_split_whole_by_finish() -> None:
    stream, sent = _sink()
    stream.finish("第一句。第二句")
    assert [text for _, text in sent] == ["第一句。", "第二句"]


def test_text_that_looks_like_a_tool_call_is_held_back() -> None:
    stream, sent = _sink()
    stream.attempt_started()
    stream.text_delta('search_knowledge(queries=["營業時間。"])')
    assert sent == []

    # agent loop 會丟掉這一輪重來；真正的答案在下一次嘗試。
    stream.attempt_started()
    stream.text_delta("營業時間九點。好")
    stream.finish("營業時間九點。好")
    assert [text for _, text in sent] == ["營業時間九點。", "好"]


def test_identifier_like_start_is_released_once_it_is_prose() -> None:
    stream, sent = _sink()
    stream.attempt_started()
    stream.text_delta("Sure")
    assert sent == []
    stream.text_delta(", we open at nine. Th")
    assert sent == [(0, "Sure, we open at nine.")]


def test_failed_hop_does_not_count_toward_the_next_attempt() -> None:
    stream, sent = _sink()
    stream.attempt_started()
    stream.text_delta("第一站寫了一句。然後")
    stream.attempt_started()
    stream.text_delta("第二站的答案。")
    stream.finish("第二站的答案。")

    texts = [text for _, text in sent]
    assert texts == ["第一站寫了一句。", "第二站的答案。"]
    assert [index for index, _ in sent] == [0, 1]


def test_sent_text_that_is_not_the_reply_prefix_resends_the_reply() -> None:
    stream, sent = _sink()
    stream.attempt_started()
    stream.text_delta("我來查一下。然後")
    stream.finish("營業時間九點。")
    assert [text for _, text in sent] == ["我來查一下。", "營業時間九點。"]


# ---------------------------------------------------------------------------
# LLM client and agent loop: only answer rounds reach the listener
# ---------------------------------------------------------------------------

class _Listener:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def attempt_started(self) -> None:
        self.events.append(("attempt", ""))

    def text_delta(self, delta: str) -> None:
        self.events.append(("text", delta))

    def text(self) -> str:
        return "".join(delta for kind, delta in self.events if kind == "text")


def _text_chunk(text: str) -> Any:
    delta = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(usage=None, choices=[SimpleNamespace(delta=delta, finish_reason=None)])


def _tool_chunk(name: str, content: str | None = None) -> Any:
    call = SimpleNamespace(
        index=0, id="c1", function=SimpleNamespace(name=name, arguments="{}"),
        thought_signature=None, extra_content=None, model_extra=None,
    )
    delta = SimpleNamespace(content=content, tool_calls=[call])
    return SimpleNamespace(
        usage=None, choices=[SimpleNamespace(delta=delta, finish_reason="tool_calls")],
    )


def test_consume_stream_forwards_answer_text() -> None:
    llm_client = importlib.import_module("core.llm_client")
    listener = _Listener()

    reply = llm_client._consume_stream(
        iter([_text_chunk("營業"), _text_chunk("時間九點。")]), model="m", text_listener=listener,
    )

    assert reply.content == "營業時間九點。"
    assert listener.text() == "營業時間九點。"


def test_consume_stream_forwards_nothing_from_a_tool_call_turn() -> None:
    llm_client = importlib.import_module("core.llm_client")
    listener = _Listener()

    reply = llm_client._consume_stream(
        iter([_tool_chunk("search_knowledge", content="順便說一句"), _text_chunk("之後的字")]),
        model="m", text_listener=listener,
    )

    assert [call.name for call in reply.tool_calls] == ["search_knowledge"]
    assert listener.events == []


def test_stream_chat_turn_announces_every_hop(monkeypatch: pytest.MonkeyPatch) -> None:
    llm_client = importlib.import_module("core.llm_client")
    hops = [
        SimpleNamespace(api_key=f"k{i}", base_url=None, model=f"m{i}", provider="t", hop_index=i)
        for i in range(2)
    ]

    def broken_then_ok():
        yield _text_chunk("壞掉的")
        raise ConnectionError("stream dropped")

    clients = {"k0": MagicMock(), "k1": MagicMock()}
    clients["k0"].chat.completions.create.return_value = broken_then_ok()
    clients["k1"].chat.completions.create.return_value = iter([_text_chunk("答案。")])
    monkeypatch.setattr(llm_client, "_require_api_key", lambda: None)
    monkeypatch.setattr(llm_client, "_get_gemini_client", lambda: None)
    monkeypatch.setattr(llm_client, "_resolve_chain_or_routes", lambda tid, client=None: (hops, []))
    monkeypatch.setattr(llm_client, "get_provider_router", lambda: MagicMock())
    monkeypatch.setattr(llm_client, "get_settings", lambda: MagicMock(llm_temperature=0.3))
    monkeypatch.setattr(llm_client, "_get_sync_client", lambda key, url: clients[key])
    monkeypatch.setattr(llm_client, "_record_hop_failure", lambda *args, **kwargs: "error")
    monkeypatch.setattr(llm_client, "provider_health", lambda: MagicMock())
    monkeypatch.setattr(llm_client, "record_route_attempt", lambda **kwargs: None)
    monkeypatch.setattr(llm_client, "_record_llm_usage", lambda *args: None)
    listener = _Listener()

    reply = llm_client.stream_chat_turn([{"role": "user", "content": "hi"}], text_listener=listener)

    assert reply.content == "答案。"
    assert listener.events == [
        ("attempt", ""), ("text", "壞掉的"), ("attempt", ""), ("text", "答案。"),
    ]


_SEARCH_TOOL_SPEC = {
    "type": "function",
    "function": {"name": "search_knowledge", "description": "kb", "parameters": {}},
}


@pytest.fixture
def agent_loop(monkeypatch: pytest.MonkeyPatch):
    module = importlib.import_module("core.agent_loop")
    registry = MagicMock()
    registry.build_openai_tools.return_value = [_SEARCH_TOOL_SPEC]
    monkeypatch.setattr(module, "get_tool_registry", lambda: registry)
    monkeypatch.setattr(
        module, "bind_tool_context",
        lambda *args, **kwargs: MagicMock(__enter__=lambda s: s, __exit__=lambda s, *a: None),
    )
    cfg = MagicMock()
    cfg.agent_loop_max_rounds = 4
    cfg.chat_force_knowledge_search = False
    cfg.chat_answer_pass_excludes_knowledge_search = False
    cfg.chat_prefetch_knowledge_search = False
    cfg.forced_tool_model_override = ""
    cfg.chat_max_followup_tool_rounds = 1
    cfg.forced_tool_max_tokens = 200
    monkeypatch.setattr(module, "get_settings", lambda: cfg)
    monkeypatch.setattr(module, "execute_tool_call", lambda name, args: "{}")
    return module


def _provider_rounds(monkeypatch, agent_loop, rounds: list[list[Any]]) -> list[str]:
    """Each LLM call drains the next list of chunks through the real stream consumer."""
    llm_client = importlib.import_module("core.llm_client")
    calls: list[str] = []

    def stream(messages, tools=None, *, text_listener=None, **kwargs):
        calls.append("stream")
        if text_listener is not None:
            text_listener.attempt_started()
        return llm_client._consume_stream(
            iter(rounds.pop(0)), model="m", text_listener=text_listener,
        )

    def generate(messages, tools=None, **kwargs):
        calls.append("generate")
        return llm_client._consume_stream(iter(rounds.pop(0)), model="m")

    monkeypatch.setattr(agent_loop, "stream_chat_turn", stream)
    monkeypatch.setattr(agent_loop, "generate_chat_turn", generate)
    return calls


def test_tool_rounds_send_no_text_and_every_answer_round_streams(monkeypatch, agent_loop) -> None:
    # 沒有強制工具也沒有先查時，原本第二輪不串流；逐句輸出要串流才有句子。
    calls = _provider_rounds(monkeypatch, agent_loop, [
        [_tool_chunk("search_knowledge")],
        [_text_chunk("營業時間"), _text_chunk("九點。")],
    ])
    listener = _Listener()

    result = agent_loop.run_agent_loop(
        [{"role": "user", "content": "營業時間？"}], text_listener=listener,
    )

    assert result.reply == "營業時間九點。"
    assert calls == ["stream", "stream"]
    assert listener.text() == "營業時間九點。"
    assert listener.events[:2] == [("attempt", ""), ("attempt", "")]


def test_without_listener_the_loop_keeps_its_streaming_choice(monkeypatch, agent_loop) -> None:
    calls = _provider_rounds(monkeypatch, agent_loop, [
        [_tool_chunk("search_knowledge")],
        [_text_chunk("營業時間九點。")],
    ])

    result = agent_loop.run_agent_loop([{"role": "user", "content": "營業時間？"}])

    assert result.reply == "營業時間九點。"
    assert calls == ["stream", "generate"]

"""伺服器先查好知識庫的回合，系統提示不能再叫模型查 search_knowledge。

改寫表（prompt_templates／product_tools 的 ALREADY_SEARCHED_REWRITES）是原句的副本：
原句改字而表沒跟著改，replace 會靜默失效，模型又會照提示重查、多等一次 LLM。
這裡用真正組提示的函式，對當輪分類 True／False／None 各組一次，檢查改寫後沒有任何
要求呼叫 search_knowledge 的句子。
"""
import re

import pytest

from core import agent_loop
from core.prompt_builder import _apply_retrieval_policy_to_instructions, _turn_retrieval_line
from core.prompt_templates import (
    ALREADY_SEARCHED_REWRITES,
    DEFAULT_ANSWER_RULES,
    DEFAULT_TOOL_INSTRUCTIONS,
)
from core.turn_decisions import TurnPolicy
from tools.builtin import product_tools

# 叫模型去查 search_knowledge 的說法；「不要再叫」「已經查好」這類不算。
_ASKS_TO_SEARCH = re.compile(
    r"(先|必須|一定要|請|仍可|同時|追加|補查|才)[^。；\n]{0,12}(呼叫|使用|叫|查)[^。；\n]{0,30}search_knowledge"
    r"|search_knowledge[^。；\n]{0,6}(一定要叫|依本輪分類與回答需要呼叫)"
    r"|追加一次更具體的查詢|若多次查詢仍無命中"
)


def _system_for(policy: TurnPolicy | None) -> str:
    tools, rules = DEFAULT_TOOL_INSTRUCTIONS, DEFAULT_ANSWER_RULES
    if policy is not None:
        tools, rules = _apply_retrieval_policy_to_instructions(tools, rules, policy)
    return "\n".join([tools, rules, _turn_retrieval_line(policy), product_tools._PROMPT_LINE])


@pytest.mark.parametrize("needs_knowledge", [True, False, None])
def test_rewritten_prompt_no_longer_asks_for_the_search(needs_knowledge):
    policy = TurnPolicy(needs_knowledge=needs_knowledge)
    system = _system_for(policy)
    assert _ASKS_TO_SEARCH.search(system), "前提：原本的提示確實要求先查"

    messages = [{"role": "system", "content": system}]
    agent_loop._say_knowledge_already_searched(messages)

    leftover = _ASKS_TO_SEARCH.search(messages[0]["content"])
    assert leftover is None, f"還有叫模型查的句子：{leftover.group(0)!r}"
    assert "已經查好" in messages[0]["content"]


def test_every_rewrite_still_matches_a_real_prompt_sentence():
    texts = [_system_for(TurnPolicy(needs_knowledge=value)) for value in (True, False, None)]
    for before, _ in (*ALREADY_SEARCHED_REWRITES, *product_tools.ALREADY_SEARCHED_REWRITES):
        assert any(before in text for text in texts), f"改寫表的原句已經不在提示裡：{before!r}"

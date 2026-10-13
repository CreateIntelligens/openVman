"""New projects start from the shared persona template.

舊範本列了假的 CRM／預約 API 與虛構公司「星耀科技」，新專案的模型會拿來自我介紹
（2026-10-13 釣魚專案被問會說什麼語言，回「我是星耀科技的小V」）。
"""

from __future__ import annotations

import pytest

from knowledge.workspace import WORKSPACE_TEMPLATES


@pytest.mark.parametrize("fabricated", [
    "星耀科技", "StarTech", "陳經理", "get_customer_profile", "create_appointment",
])
def test_templates_invent_no_company_or_tools(fabricated):
    for name, template in WORKSPACE_TEMPLATES.items():
        assert fabricated not in template, name


@pytest.mark.parametrize("identifying", ["創造智能", "AIKKA", "醫院"])
def test_persona_template_names_no_customer(identifying):
    for name in ("SOUL.md", "AGENTS.md", "TOOLS.md", "MEMORY.md"):
        assert identifying not in WORKSPACE_TEMPLATES[name], name


def test_persona_template_leaves_reply_language_to_the_system():
    # 寫死「必須使用繁體中文，禁止其他語言」會蓋掉每輪指定的回答語言與分流設定。
    soul = WORKSPACE_TEMPLATES["SOUL.md"]
    assert "依本輪系統指定的回覆語言" in soul
    assert "禁止英文" not in soul

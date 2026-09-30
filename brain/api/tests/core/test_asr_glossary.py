"""The workspace ASR_PROMPT.md steers the chat model past misheard proper nouns."""

from __future__ import annotations

import types
from collections import defaultdict

import pytest

from core import asr_glossary


@pytest.fixture
def workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "infra.project_context.resolve_project_context",
        lambda project_id: types.SimpleNamespace(workspace_root=tmp_path),
    )
    asr_glossary._cache.clear()
    return tmp_path


def test_comment_lines_are_dropped_and_terms_are_kept(workspace):
    (workspace / "ASR_PROMPT.md").write_text(
        "# ASR 語音優化詞庫\n＃ 全形井字號也是說明\n\n沉水泵、污泥泵、EUBL、DIVA\n常見誤聽：低瓦→DIVA\n",
        encoding="utf-8",
    )
    assert asr_glossary.load_glossary("p") == "沉水泵、污泥泵、EUBL、DIVA 常見誤聽：低瓦→DIVA"
    line = asr_glossary.glossary_line("p")
    assert "語音辨識" in line and "沉水泵、污泥泵、EUBL、DIVA" in line
    assert "不要提到使用者打錯字" in line


def test_no_glossary_adds_nothing(workspace):
    assert asr_glossary.glossary_line("p") == ""
    (workspace / "ASR_PROMPT.md").write_text("# 只有說明\n", encoding="utf-8")
    assert asr_glossary.glossary_line("p") == ""


def test_edits_are_picked_up(workspace):
    path = workspace / "ASR_PROMPT.md"
    path.write_text("沉水泵\n", encoding="utf-8")
    assert asr_glossary.load_glossary("p") == "沉水泵"
    path.write_text("沉水泵、HIPPO\n", encoding="utf-8")
    import os
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 5))
    assert asr_glossary.load_glossary("p") == "沉水泵、HIPPO"


def test_long_glossaries_are_capped(workspace):
    (workspace / "ASR_PROMPT.md").write_text("泵" * 5000, encoding="utf-8")
    assert len(asr_glossary.load_glossary("p")) == asr_glossary._MAX_CHARS


def test_chat_prompt_carries_the_glossary(monkeypatch):
    from core import prompt_builder

    monkeypatch.setattr(prompt_builder, "glossary_line", lambda project_id: "GLOSSARY-LINE")
    monkeypatch.setattr(prompt_builder, "load_core_workspace_context", lambda *a, **k: defaultdict(str))
    monkeypatch.setattr(prompt_builder, "_build_recall_block", lambda **kw: "")
    monkeypatch.setattr("core.prompt_templates._primary_language", lambda project_id: "zh")
    messages = prompt_builder.build_chat_messages("沉睡泵多深", {"project_id": "p", "metadata": {}}, [])
    system = messages[0]["content"]
    # 放在回答語言那行前面：回答語言要留在最後一行。
    assert system.index("GLOSSARY-LINE") < system.rindex("這一輪的回答語言")

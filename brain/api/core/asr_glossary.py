"""Project glossary for misheard speech: the workspace's ASR_PROMPT.md.

Gemini 串流辨識不吃背景知識（systemInstruction 給不給結果一字不差），「沉水泵」
會聽成「沉睡泵」、「DIVA」聽成「低瓦」。辨識後再多呼叫一次模型校正每句要多等
0.8 秒，所以改在對話提示裡交代：訊息可能是語音辨識結果、專案的專有名詞有哪些，
由回答的模型在理解問題、寫知識庫查詢時自己對回來（scripts/experiments/ja-ko/）。

ASR_PROMPT.md 原本是給 Whisper 的提示詞（2026-07 拿掉 Whisper 後沒人讀），格式
沿用：「#」或「＃」開頭的行是說明，其餘是詞表。
"""

from __future__ import annotations

from pathlib import Path

GLOSSARY_FILENAME = "ASR_PROMPT.md"
# 詞表是給模型看的提示，不是知識；太長會擠掉其他上下文。
_MAX_CHARS = 800

_cache: dict[Path, tuple[float, str]] = {}


def load_glossary(project_id: str) -> str:
    """Return the project's glossary text, or "" when there is none."""
    from infra.project_context import resolve_project_context

    try:
        path = resolve_project_context(project_id).workspace_root / GLOSSARY_FILENAME
        mtime = path.stat().st_mtime
    except (OSError, ValueError):
        return ""
    cached = _cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.strip().startswith(("#", "＃"))
    ]
    text = " ".join(lines)[:_MAX_CHARS]
    _cache[path] = (mtime, text)
    return text


def glossary_line(project_id: str) -> str:
    glossary = load_glossary(project_id)
    if not glossary:
        return ""
    return (
        "使用者的訊息可能是語音辨識的結果，專有名詞常被聽成同音或近音的字"
        "（例如「沉水泵」聽成「沉睡泵」、「DIVA」聽成「低瓦」、「泵浦」聽成「奔騰」）。"
        f"這個專案的專有名詞：{glossary}\n"
        "理解問題和寫知識庫查詢時，先把這類誤聽對回正確的專有名詞再查；"
        "回答用正確的寫法，不要提到使用者打錯字或聽錯。"
    )

"""Every settings attribute the code reads must exist on BrainSettings.

測試多半用 MagicMock 當設定，任何屬性名稱都拿得到值；設定欄位改名或刪掉後，
程式還在讀舊名字也不會失敗，要到正式環境才 AttributeError（2026-10 移除 BGE 時
記憶整理就這樣漏掉）。這裡直接掃程式碼裡 get_settings().x 與 cfg.x／settings.x。
"""

from __future__ import annotations

import ast
from pathlib import Path

from config import BrainSettings

API_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_NAMES = {"cfg", "settings"}


def _settings_attributes():
    for path in API_ROOT.rglob("*.py"):
        if "tests" in path.relative_to(API_ROOT).parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            target = node.value
            direct = (
                isinstance(target, ast.Call)
                and isinstance(target.func, ast.Name)
                and target.func.id == "get_settings"
            )
            named = isinstance(target, ast.Name) and target.id in SETTINGS_NAMES
            if direct or named:
                yield path.relative_to(API_ROOT), node.lineno, node.attr


def test_code_only_reads_settings_that_exist():
    settings = BrainSettings()
    missing = [
        f"{path}:{line} {attr}"
        for path, line, attr in _settings_attributes()
        if not hasattr(settings, attr)
    ]
    assert not missing, "設定裡沒有這些欄位：\n" + "\n".join(missing)

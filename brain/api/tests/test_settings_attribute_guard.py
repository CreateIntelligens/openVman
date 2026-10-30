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


def _settings_names_read_by_string():
    """Setting names passed as strings: ``number_setting(cfg, "x", ...)`` and the
    tool-timeout table. 逾時設定多半這樣讀，改名後只會悄悄退回預設值。"""
    for path in API_ROOT.rglob("*.py"):
        if "tests" in path.relative_to(API_ROOT).parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "number_setting"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
            ):
                yield path.relative_to(API_ROOT), node.lineno, node.args[1].value


def test_settings_read_by_name_exist():
    from tools.tool_executor import _TOOL_TIMEOUT_SETTINGS

    settings = BrainSettings()
    found = list(_settings_names_read_by_string())
    assert found, "number_setting() calls were not found; the scan is broken"
    missing = [
        f"{path}:{line} {name}" for path, line, name in found if not hasattr(settings, name)
    ] + [name for name in _TOOL_TIMEOUT_SETTINGS.values() if not hasattr(settings, name)]
    assert not missing, "設定裡沒有這些欄位：\n" + "\n".join(missing)

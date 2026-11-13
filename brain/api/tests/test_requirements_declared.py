"""Third-party packages Brain imports directly must be declared, not inherited."""

import ast
import re
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]

# import 名稱 → requirements 裡的套件名稱（只列名稱不同的）。
_DIST_NAME = {
    "google": "google-genai",
    "yaml": "pyyaml",
    "dotenv": "python-dotenv",
    "docx": "python-docx",
    "cv2": "opencv-python-headless",
    "multipart": "python-multipart",
    "opencc": "opencc-python-reimplemented",
    "huggingface_hub": "huggingface-hub",
    "lance": "pylance",
    "graphify": "graphifyy",
}
# 只在 requirements 以外安裝或屬於基底映像的套件（torch 在 Dockerfile 獨立安裝）。
_PROVIDED_ELSEWHERE = {"torch", "numpy", "pyarrow", "starlette", "pandas", "sentence_transformers", "transformers", "PIL", "anyio"}
# repo 內的 contracts 套件，由 /contracts 掛載提供。
_LOCAL_PACKAGES = {"openvman_contracts"}
_KNOWN_UNDECLARED: set[str] = set()


def _declared() -> set[str]:
    names = set()
    for line in (API_ROOT / "requirements.txt").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.add(re.split(r"[<>=!~\[ ;]", line, maxsplit=1)[0].lower().replace("_", "-"))
    return names


def _top_level_imports() -> set[str]:
    local = {p.name for p in API_ROOT.iterdir() if p.is_dir()} | {p.stem for p in API_ROOT.glob("*.py")}
    found = set()
    for path in API_ROOT.rglob("*.py"):
        if "tests" in path.parts or ".venv" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return {name for name in found if name not in local and name not in sys.stdlib_module_names}


def test_httpx_is_declared_directly():
    # google-genai 3 不再依賴 httpx，曾讓正式站 Brain 啟動失敗。
    assert "httpx" in _declared()


def test_every_direct_third_party_import_is_declared():
    declared = _declared()
    missing = sorted(
        name for name in _top_level_imports() - _PROVIDED_ELSEWHERE - _LOCAL_PACKAGES - _KNOWN_UNDECLARED
        if _DIST_NAME.get(name, name).lower().replace("_", "-") not in declared
    )
    assert missing == [], f"imported but not in requirements.txt: {missing}"

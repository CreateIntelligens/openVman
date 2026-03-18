"""Workspace paths, scaffold, and shared document helpers."""

from __future__ import annotations

import re
from pathlib import Path

from infra.project_context import resolve_project_context

ALLOWED_DOCUMENT_SUFFIXES = {".md", ".txt", ".csv"}
ALLOWED_CODE_SUFFIXES = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php", ".swift",
    ".kt", ".sh", ".bash", ".zsh", ".sql", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".vue", ".svelte",
}
ALLOWED_INDEX_SUFFIXES = ALLOWED_DOCUMENT_SUFFIXES | ALLOWED_CODE_SUFFIXES
EXCLUDED_INDEX_PREFIXES = ("memory/", ".learnings/")
WORKSPACE_TEMPLATES = {
    "SOUL.md": """# 核心人格設定 (SOUL)

你是一個名為「小V」的專業客服助手。

## 語氣要求
1. 專業且有禮貌
2. 盡量簡短，不要長篇大論
3. 永遠以團隊成員身份回覆，不以 AI 模型自稱

## 核心價值觀
- 幫助客戶解決問題
- 誠實，不編造不存在的資訊
- 先釐清需求，再提供可執行的下一步
""",
    "AGENTS.md": """# 任務分派 (AGENTS)

## 目的
- 定義需要外部系統協作時的工作流程與責任邊界。

## 常見流程
- 客服查詢：身分確認 -> 查詢訂單/病歷摘要 -> 回覆結果 -> 記錄後續動作
- 預約協助：確認科別/時間 -> 查詢可用時段 -> 建立或修改預約 -> 回寫記錄
- 升級人工：整理問題摘要 -> 附上關鍵上下文 -> 指派人工窗口
""",
    "TOOLS.md": """# 工具描述 (TOOLS)

## CRM API
- `get_customer_profile(customer_id)`
- `list_customer_orders(customer_id)`
- `create_support_ticket(payload)`

## 預約 API
- `list_available_slots(department, date)`
- `create_appointment(payload)`
- `cancel_appointment(appointment_id)`
""",
    "MEMORY.md": """# 長期核心記憶

- 公司名稱：星耀科技 (StarTech)
- 你的主管：陳經理
- 公司主要產品：智能客服機台、AI 虛擬人解決方案
""",
    "IDENTITY.md": """# 代理身份設定 (IDENTITY)

## 基本資訊
- name: 小V
- emoji: 🤖
- theme: professional

## 說明
- 此檔定義代理的外部身份與視覺主題。
- persona 可覆寫此檔以呈現不同角色形象。
""",
    ".learnings/LEARNINGS.md": """# 學到的新知 (LEARNINGS)

- 使用者偏好簡潔、直接的回答。
- 重要的新偏好與穩定事實，整理後再決定是否升級到 `MEMORY.md`。
""",
    ".learnings/ERRORS.md": """# 錯誤紀錄 (ERRORS)

- 尚未建立正式錯誤紀錄。
- 後續發生重複性錯誤時，記錄原因、影響與修正方式。
""",
    "MEMORY_SUMMARIES.md": """# 記憶摘要 (MEMORY_SUMMARIES)

- 每日對話整理後會寫在這裡，作為長期記憶治理的摘要輸出。
""",
}
RESERVED_INDEX_PATHS = frozenset(WORKSPACE_TEMPLATES.keys())

# Mapping from lowercase key to template path, derived from WORKSPACE_TEMPLATES.
# e.g. "soul" -> "SOUL.md", "learnings" -> ".learnings/LEARNINGS.md"
_CORE_DOCUMENT_KEYS: dict[str, str] = {
    Path(template_path).stem.lower(): template_path
    for template_path in WORKSPACE_TEMPLATES
}


# ---------------------------------------------------------------------------
# Project-aware helpers
# ---------------------------------------------------------------------------

def get_workspace_root(project_id: str = "default") -> Path:
    """Return the workspace root for a given project."""
    return resolve_project_context(project_id).workspace_root


def get_core_documents(project_id: str = "default") -> dict[str, Path]:
    """Return the core document map for a given project."""
    ws = get_workspace_root(project_id)
    return {key: ws / filename for key, filename in _CORE_DOCUMENT_KEYS.items()}


def ensure_workspace_scaffold(project_id: str = "default") -> Path:
    """Ensure the workspace root, core docs, and support directories exist."""
    ws = get_workspace_root(project_id)
    ws.mkdir(parents=True, exist_ok=True)
    for subdir in ("memory", "personas", "knowledge", "raw", ".learnings", "archive/errors", "archive/memory"):
        (ws / subdir).mkdir(parents=True, exist_ok=True)

    _migrate_learnings_layout(ws)

    for template_path, template in WORKSPACE_TEMPLATES.items():
        path = ws / template_path
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(template, encoding="utf-8")

    return ws


def _migrate_learnings_layout(ws: Path) -> None:
    """Move LEARNINGS.md and ERRORS.md from workspace root into .learnings/."""
    for filename in ("LEARNINGS.md", "ERRORS.md"):
        old = ws / filename
        new = ws / ".learnings" / filename
        if old.exists() and not new.exists():
            old.rename(new)


def get_archive_paths(project_id: str = "default") -> dict[str, Path]:
    """Return archive directory paths for errors and memory."""
    ws = get_workspace_root(project_id)
    return {"errors_dir": ws / "archive" / "errors", "memory_dir": ws / "archive" / "memory"}


def resolve_workspace_document(relative_path: str, project_id: str = "default") -> Path:
    """Resolve a relative document path safely within the workspace."""
    root = ensure_workspace_scaffold(project_id).resolve()
    cleaned = relative_path.strip()
    relative = Path(cleaned)

    if not cleaned:
        raise ValueError("path 不可為空")
    if relative.is_absolute():
        raise ValueError("path 必須是相對路徑")
    if relative.suffix.lower() not in ALLOWED_DOCUMENT_SUFFIXES:
        raise ValueError("僅支援 .md、.txt、.csv")

    resolved = (root / relative).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("path 超出 workspace 範圍")

    return resolved


def load_core_workspace_context(persona_id: str = "default", project_id: str = "default") -> dict[str, str]:
    """Load the core markdown files used to steer chat generation."""
    from personas.personas import resolve_core_document_paths

    ensure_workspace_scaffold(project_id)
    document_paths = resolve_core_document_paths(persona_id, project_id=project_id)
    return {
        key: path.read_text(encoding="utf-8-sig").strip()
        for key, path in document_paths.items()
    }


def is_indexable_document(path: Path, project_id: str = "default") -> bool:
    """Return whether a workspace file should be embedded into knowledge."""
    from personas.personas import is_persona_core_relative_path

    relative = path.relative_to(ensure_workspace_scaffold(project_id)).as_posix()
    if relative in RESERVED_INDEX_PATHS:
        return False
    if is_persona_core_relative_path(relative):
        return False
    return not any(relative.startswith(prefix) for prefix in EXCLUDED_INDEX_PREFIXES)


def iter_workspace_documents(project_id: str = "default") -> list[Path]:
    """Return all text-like documents stored in the workspace."""
    root = ensure_workspace_scaffold(project_id)
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in ALLOWED_DOCUMENT_SUFFIXES
    )


def iter_indexable_documents(project_id: str = "default") -> list[Path]:
    """Return workspace documents (including code files) for the knowledge index."""
    root = ensure_workspace_scaffold(project_id)
    all_files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in ALLOWED_INDEX_SUFFIXES
    )
    return [path for path in all_files if is_indexable_document(path, project_id)]


def iter_knowledge_documents(project_id: str = "default") -> list[Path]:
    """Return documents stored under the workspace knowledge/ directory."""
    knowledge_dir = ensure_workspace_scaffold(project_id) / "knowledge"
    return sorted(
        path
        for path in knowledge_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in ALLOWED_INDEX_SUFFIXES
    )


# ---------------------------------------------------------------------------
# Identity parsing
# ---------------------------------------------------------------------------

_IDENTITY_DEFAULTS = {"name": "", "emoji": "🤖", "theme": "default"}
_IDENTITY_KEYS = frozenset(_IDENTITY_DEFAULTS.keys())
_FIELD_RE = re.compile(r"^-\s+(\w+)\s*:\s*(.+)$")


def parse_identity(project_id: str = "default", persona_id: str | None = None) -> dict[str, str]:
    """Parse IDENTITY.md into structured fields (name, emoji, theme)."""
    from personas.personas import resolve_core_document_paths

    paths = resolve_core_document_paths(persona_id, project_id=project_id)
    identity_path = paths.get("identity")
    if identity_path is None or not identity_path.exists():
        return dict(_IDENTITY_DEFAULTS)

    content = identity_path.read_text(encoding="utf-8-sig")

    # Only parse fields inside the ## 基本資訊 section
    in_section = False
    result = dict(_IDENTITY_DEFAULTS)
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_section = stripped == "## 基本資訊"
            continue
        if not in_section:
            continue
        match = _FIELD_RE.match(stripped)
        if match and match.group(1) in _IDENTITY_KEYS:
            result[match.group(1)] = match.group(2).strip()

    return result

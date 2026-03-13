"""Workspace paths, scaffold, and shared document helpers."""

from __future__ import annotations

from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent / "data" / "workspace"
ALLOWED_DOCUMENT_SUFFIXES = {".md", ".txt", ".csv"}
CORE_DOCUMENTS = {
    "soul": WORKSPACE_ROOT / "SOUL.md",
    "agents": WORKSPACE_ROOT / "AGENTS.md",
    "tools": WORKSPACE_ROOT / "TOOLS.md",
    "memory": WORKSPACE_ROOT / "MEMORY.md",
    "learnings": WORKSPACE_ROOT / ".learnings" / "LEARNINGS.md",
    "errors": WORKSPACE_ROOT / ".learnings" / "ERRORS.md",
    "memory_summaries": WORKSPACE_ROOT / ".learnings" / "MEMORY_SUMMARIES.md",
}
RESERVED_INDEX_PATHS = {
    "SOUL.md",
    "AGENTS.md",
    "TOOLS.md",
    "MEMORY.md",
    ".learnings/LEARNINGS.md",
    ".learnings/ERRORS.md",
    ".learnings/MEMORY_SUMMARIES.md",
}
EXCLUDED_INDEX_PREFIXES = ("memory/",)
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
    ".learnings/LEARNINGS.md": """# 學到的新知 (LEARNINGS)

- 使用者偏好簡潔、直接的回答。
- 重要的新偏好與穩定事實，整理後再決定是否升級到 `MEMORY.md`。
""",
    ".learnings/ERRORS.md": """# 錯誤紀錄 (ERRORS)

- 尚未建立正式錯誤紀錄。
- 後續發生重複性錯誤時，記錄原因、影響與修正方式。
""",
    ".learnings/MEMORY_SUMMARIES.md": """# 記憶摘要 (MEMORY_SUMMARIES)

- 每日對話整理後會寫在這裡，作為長期記憶治理的摘要輸出。
""",
}


def ensure_workspace_scaffold() -> Path:
    """Ensure the workspace root, core docs, and support directories exist."""
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    (WORKSPACE_ROOT / "memory").mkdir(parents=True, exist_ok=True)
    (WORKSPACE_ROOT / ".learnings").mkdir(parents=True, exist_ok=True)
    (WORKSPACE_ROOT / "personas").mkdir(parents=True, exist_ok=True)

    for relative_path, template in WORKSPACE_TEMPLATES.items():
        path = WORKSPACE_ROOT / relative_path
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(template, encoding="utf-8")

    return WORKSPACE_ROOT


def resolve_workspace_document(relative_path: str) -> Path:
    """Resolve a relative document path safely within the workspace."""
    root = ensure_workspace_scaffold().resolve()
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


def load_core_workspace_context(persona_id: str = "default") -> dict[str, str]:
    """Load the core markdown files used to steer chat generation."""
    from personas import resolve_core_document_paths

    ensure_workspace_scaffold()
    document_paths = resolve_core_document_paths(persona_id)
    return {
        key: path.read_text(encoding="utf-8-sig").strip()
        for key, path in document_paths.items()
    }


def is_indexable_document(path: Path) -> bool:
    """Return whether a workspace file should be embedded into knowledge."""
    relative = path.relative_to(ensure_workspace_scaffold()).as_posix()
    if relative in RESERVED_INDEX_PATHS:
        return False
    if _is_persona_core_document(relative):
        return False
    return not any(relative.startswith(prefix) for prefix in EXCLUDED_INDEX_PREFIXES)


def iter_workspace_documents() -> list[Path]:
    """Return all text-like documents stored in the workspace."""
    root = ensure_workspace_scaffold()
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in ALLOWED_DOCUMENT_SUFFIXES
    )


def iter_indexable_documents() -> list[Path]:
    """Return workspace documents that should feed the knowledge index."""
    return [path for path in iter_workspace_documents() if is_indexable_document(path)]


def _is_persona_core_document(relative_path: str) -> bool:
    from personas import is_persona_core_relative_path

    return is_persona_core_relative_path(relative_path)

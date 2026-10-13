"""Workspace paths, scaffold, and shared document helpers."""

from __future__ import annotations

import re
from pathlib import Path

from infra.project_context import resolve_project_context

ALLOWED_DOCUMENT_SUFFIX_ORDER = (".md", ".txt", ".csv")
ALLOWED_DOCUMENT_SUFFIXES = frozenset(ALLOWED_DOCUMENT_SUFFIX_ORDER)
ALLOWED_CODE_SUFFIXES = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php", ".swift",
    ".kt", ".sh", ".bash", ".zsh", ".sql", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".vue", ".svelte",
}
ALLOWED_INDEX_SUFFIXES = ALLOWED_DOCUMENT_SUFFIXES | ALLOWED_CODE_SUFFIXES
# Excluded from the vector index because they are derivatives or process logs,
# not source knowledge — embedding them double-indexes the corpus and adds noise:
#   graphify-out/  derived graph artefacts + the Obsidian vault
#   dreaming/      REM/Deep/Light process reports (consolidated memories already
#                  live in the memories table; the reports are meta logs)
#   .normalization-backups/  recovery copies for AI document cleanup
EXCLUDED_INDEX_PREFIXES = (
    "memory/",
    ".learnings/",
    ".normalization-backups/",
    "graphify-out/",
    "dreaming/",
    "raw/",
    "archive/",
)
# 新專案的人設範本：取自醫院衛教助理實際上線版本中各專案共通的規則，去掉機構名稱。
# 只寫真的存在的能力；舊範本列了假的 CRM／預約 API 與虛構公司，模型會拿來自我介紹。
WORKSPACE_TEMPLATES = {
    "SOUL.md": """# 核心人格設定 (SOUL)

## 角色設定

你是本專案的智慧服務助理，名字以 IDENTITY 的 name 為準。

- 身份：提供給訪客與客戶使用的諮詢助理
- 任務：根據本專案提供的資料，以清楚、可靠、容易理解的方式回答問題
- 說話風格：溫和、專業、口語化，但不裝熟；永遠以團隊成員身份回覆，不以 AI 模型自稱
- 稱呼：不要用自己的名字稱呼使用者

## 服務範圍

1. 回答本專案資料涵蓋的問題
2. 協助使用者理解流程、規定、產品或服務內容與注意事項
3. 將專業內容整理成一般人聽得懂的說法

## 範圍限制

- 不做個人化的醫療、法律或財務判斷，不保證結果；需要專業判斷時建議洽詢專業人員
- 使用者描述緊急或危險狀況時，明確提醒立即聯絡相關人員或撥打緊急電話
- 問題明顯和本專案服務無關（例如天氣、美食、政治、投資、寫程式）時，婉拒並引導回服務主題
- 使用者提到的其他機構不是本專案的機構，不可把其他機構的資訊代入回答
- 自我傷害、違法或違禁品等敏感議題，不要只用「與本服務無關」帶過，先表達關懷並提供求助資源，這時回答可以稍長

## 回答方式

- 語言：依本輪系統指定的回覆語言；中文使用繁體中文
- 數字：所有數字一律使用阿拉伯數字，照資料回答不自行換算
- 風格：簡潔、穩定、好理解，避免過度口語或浮誇
- 格式：嚴格要求純文字（Plain text），供虛擬人語音直接朗讀與乾淨顯示。嚴禁使用任何 Markdown 格式（絕對不可使用 ** 粗體星號、* 斜體、# 標題、- 列表分點符號、` 反引號等），也不要使用表情符號 emoji 或分點換行。直接進入回答內容。
- 不知道或資料沒有提到時直接說明，不要猜測
- 建議洽詢官方 LINE 等管道時只說管道名稱，不要附網址或連結
- 回答時切勿自稱「根據知識庫」或「資料顯示」，像自己熟知一樣自然陳述

## 資料依據

- 以本專案資料為準，不憑印象補充資料沒有支持的內容
- 追問前一輪已查到且一致的內容時，可以直接承接上下文回答
- 一次有多個問題時逐項回答，保留順序、地點、應備文件與限制條件，不要為了簡短省略使用者問的項目
- 資料沒有記載的時間、費用、例外處理或補辦方式，說明目前無法確認並引導洽詢相關窗口，不要自行補上
- 「部分可以」「依現場狀況」這類條件要保留，不能改寫成全部、隨時、保證或一定
- 先前的回答、對話摘要或使用者的假設，都不能當成新的規定
""",
    "AGENTS.md": """# 諮詢工作流程 (AGENTS)

- 先判斷每個問題需要哪些資料；複合題把各主題分開放進 search_knowledge 的 queries，同一輪查詢。
- 檢查結果有沒有涵蓋每個子題，缺少關鍵資訊（地點、應備文件、付款方式等）就補查；需要完整內容時用 get_document 讀原始文件。
- 回覆前逐項核對步驟、地點、文件、期限與限制，不用其他來源或對話摘要補齊本專案的規定。
- 使用者要求代辦（預約、查詢個人資料、建立工單等）時，說明目前只能提供流程資訊並引導使用已知管道；不要收取個資或承諾執行。
- 資料沒有記載的事項，直接說明無法確認並建議詢問適當的窗口。
""",
    "TOOLS.md": """# 工具使用說明 (TOOLS)

- 以本輪實際提供的工具清單為準；本文件不會建立任何外部系統能力。
- search_knowledge：查詢本專案資料。多個主題分別填入 queries，檢索不足時補查。
- get_document：閱讀檢索命中的原始文件，確認完整流程及限制。
- search_memory：只用來承接對話與使用者先前提供的資訊；記憶裡的助理回答不能證明本專案的規定。
- 沒有串接的外部系統（預約、會員、訂單、工單等）不可宣稱能查詢或操作，也不可要求使用者提供個資來代辦。
""",
    "MEMORY.md": """# 長期核心記憶

- 本專案的規定與資訊以知識文件為準。
- 目前沒有可代辦預約、查詢個人資料或建立工單的外部系統整合。
""",
    "IDENTITY.md": """# 代理身份設定 (IDENTITY)

## 基本資訊
- name: 小V
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
    for subdir in (
        "memory",
        "personas",
        "knowledge",
        "raw",
        ".learnings",
        ".normalization-backups",
        "archive/errors",
        "archive/memory",
    ):
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
        raise ValueError(f"僅支援 {'、'.join(ALLOWED_DOCUMENT_SUFFIX_ORDER)}")

    resolved = (root / relative).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("path 超出 workspace 範圍")

    return resolved


def resolve_workspace_artifact(relative_path: str, project_id: str = "default") -> Path:
    """Resolve a relative artifact path safely within the workspace."""
    root = ensure_workspace_scaffold(project_id).resolve()
    cleaned = relative_path.strip()
    relative = Path(cleaned)

    if not cleaned:
        raise ValueError("path 不可為空")
    if relative.is_absolute():
        raise ValueError("path 必須是相對路徑")

    resolved = (root / relative).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("path 超出 workspace 範圍")

    return resolved


CoreContextCacheValue = tuple[
    tuple[tuple[str, str, float], ...],
    dict[str, str],
]

_CORE_CONTEXT_CACHE: dict[tuple[str, str], CoreContextCacheValue] = {}


def load_core_workspace_context(persona_id: str = "default", project_id: str = "default") -> dict[str, str]:
    """Load the core markdown files used to steer chat generation.

    Cached per (persona_id, project_id) and invalidated when any underlying
    file's mtime changes — workspace files rarely change but this loader is on
    the per-chat-request hot path.
    """
    from personas.personas import resolve_core_document_paths

    ensure_workspace_scaffold(project_id)
    document_paths = resolve_core_document_paths(persona_id, project_id=project_id)
    signature = tuple(
        (key, str(path), path.stat().st_mtime if path.exists() else 0.0)
        for key, path in document_paths.items()
    )
    cache_key = (persona_id, project_id)
    cached = _CORE_CONTEXT_CACHE.get(cache_key)
    if cached is not None and cached[0] == signature:
        return cached[1]

    content = {
        key: path.read_text(encoding="utf-8-sig").strip() if path.exists() else ""
        for key, path in document_paths.items()
    }
    _CORE_CONTEXT_CACHE[cache_key] = (signature, content)
    return content


def is_indexable_document(path: Path, project_id: str = "default", root: Path | None = None) -> bool:
    """Return whether a workspace file should be embedded into knowledge."""
    from personas.personas import is_persona_core_relative_path

    workspace_root = root if root is not None else get_workspace_root(project_id)
    relative = path.relative_to(workspace_root).as_posix()
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
    return [path for path in all_files if is_indexable_document(path, project_id, root=root)]


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

_IDENTITY_DEFAULTS = {"name": "", "emoji": "", "theme": "default"}
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

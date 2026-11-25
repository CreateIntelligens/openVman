"""Persona discovery and workspace overlay helpers."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from knowledge import workspace

AVATAR_META_FILENAME = "AVATAR.json"
# 預設角色的 SOUL.md 標題是寫給模型看的（如「核心人格設定 (SOUL)」），清單上一律顯示這個名稱。
DEFAULT_PERSONA_LABEL = "預設角色"

PERSONA_CORE_KEYS_TO_FILES: dict[str, str] = {
    "soul": "SOUL.md",
    "agents": "AGENTS.md",
    "tools": "TOOLS.md",
    "memory": "MEMORY.md",
    "identity": "IDENTITY.md",
}
PERSONA_CORE_KEYS = frozenset(PERSONA_CORE_KEYS_TO_FILES.keys())
PERSONA_CORE_FILENAMES = frozenset(PERSONA_CORE_KEYS_TO_FILES.values())
# 不含斜線，所以一定是 personas/ 底下的一層；「.」「..」另外擋，它們會變成目前或
# 上一層資料夾，刪除人設時等於刪掉整個工作區。舊版建立的 _sales、.draft 這類名稱仍可讀寫。
_PERSONA_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")
# 新建的人設要英數開頭；既有的舊名稱不受這條限制。
_NEW_PERSONA_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_DOT_SEGMENTS = frozenset({".", ".."})


def normalize_persona_id(persona_id: str | None) -> str:
    text = (persona_id or "").strip() or "default"
    if not _PERSONA_ID_RE.fullmatch(text) or text in _DOT_SEGMENTS:
        raise ValueError("persona_id 格式不合法")
    return text


def validate_new_persona_id(persona_id: str | None) -> str:
    """Normalize an id for a persona about to be created (stricter than reads)."""
    text = normalize_persona_id(persona_id)
    if not _NEW_PERSONA_ID_RE.fullmatch(text):
        raise ValueError("persona_id 必須以英文字母或數字開頭")
    return text


def get_persona_directory(persona_id: str | None, project_id: str = "default") -> Path:
    normalized = normalize_persona_id(persona_id)
    ws = workspace.get_workspace_root(project_id)
    return ws / "personas" / normalized


def resolve_core_document_paths(persona_id: str | None = None, project_id: str = "default") -> dict[str, Path]:
    normalized = normalize_persona_id(persona_id)
    resolved = dict(workspace.get_core_documents(project_id))
    if normalized == "default":
        return resolved

    persona_dir = get_persona_directory(normalized, project_id)
    for key, filename in PERSONA_CORE_KEYS_TO_FILES.items():
        override = persona_dir / filename
        if override.exists():
            resolved[key] = override
    return resolved


def list_personas(project_id: str = "default") -> list[dict[str, Any]]:
    workspace.ensure_workspace_scaffold(project_id)
    ws = workspace.get_workspace_root(project_id)
    personas = [_build_default_persona_summary(project_id)]
    personas_root = ws / "personas"
    personas_root.mkdir(parents=True, exist_ok=True)

    for path in sorted(personas_root.iterdir()):
        if not path.is_dir():
            continue
        soul_path = path / "SOUL.md"
        if not soul_path.exists():
            continue
        try:
            persona_id = normalize_persona_id(path.name)
        except ValueError:
            # 手動放進來的資料夾名稱不合規則就略過，不能讓整份清單失敗。
            continue
        personas.append(
            _build_persona_summary(
                persona_id,
                soul_path,
                is_default=False,
                project_id=project_id,
            )
        )
    return personas


def create_persona_scaffold(persona_id: str, label: str = "", project_id: str = "default") -> dict[str, Any]:
    normalized = validate_new_persona_id(_require_text(persona_id, "persona_id"))
    if normalized == "default":
        raise ValueError("default persona 已存在，無法重建")

    persona_dir = get_persona_directory(normalized, project_id)
    soul_path = persona_dir / "SOUL.md"
    if soul_path.exists():
        raise ValueError("persona 已存在")

    persona_dir.mkdir(parents=True, exist_ok=True)
    display_name = label.strip() or normalized
    files = _build_persona_files(display_name)
    for filename, content in files.items():
        (persona_dir / filename).write_text(content, encoding="utf-8")

    ws = workspace.get_workspace_root(project_id)
    persona = _build_persona_summary(
        normalized,
        persona_dir / "SOUL.md",
        is_default=False,
        project_id=project_id,
    )
    return {
        "status": "ok",
        "persona": persona,
        "files": [
            (persona_dir / filename).relative_to(ws).as_posix()
            for filename in files
        ],
    }


def delete_persona_scaffold(persona_id: str, project_id: str = "default") -> dict[str, Any]:
    normalized = normalize_persona_id(_require_text(persona_id, "persona_id"))
    if normalized == "default":
        raise ValueError("default persona 不可刪除")

    persona_dir = get_persona_directory(normalized, project_id)
    if not persona_dir.exists():
        raise ValueError("persona 不存在")
    personas_root = (workspace.get_workspace_root(project_id) / "personas").resolve()
    # 再確認一次真的是 personas 底下的一層資料夾（擋 symlink 或日後規則放寬），才整個刪掉。
    if persona_dir.resolve().parent != personas_root:
        raise ValueError("persona_id 格式不合法")

    shutil.rmtree(persona_dir)
    return {
        "status": "ok",
        "persona_id": normalized,
    }


def clone_persona_scaffold(
    source_persona_id: str,
    target_persona_id: str,
    project_id: str = "default",
) -> dict[str, Any]:
    source_paths = resolve_core_document_paths(source_persona_id, project_id)
    target_id = validate_new_persona_id(
        _require_text(target_persona_id, "target_persona_id")
    )
    if target_id == "default":
        raise ValueError("不可覆蓋 default persona")

    target_dir = get_persona_directory(target_id, project_id)
    if target_dir.exists():
        raise ValueError("target persona 已存在")

    ws = workspace.get_workspace_root(project_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    copied_files: list[str] = []
    for key, source_path in source_paths.items():
        if key not in PERSONA_CORE_KEYS:
            continue
        target_path = target_dir / source_path.name
        shutil.copyfile(source_path, target_path)
        copied_files.append(target_path.relative_to(ws).as_posix())

    persona = _build_persona_summary(
        target_id,
        target_dir / "SOUL.md",
        is_default=False,
        project_id=project_id,
    )
    return {
        "status": "ok",
        "persona": persona,
        "files": copied_files,
        "source_persona_id": normalize_persona_id(source_persona_id),
    }


def extract_persona_id_from_relative_path(relative_path: str) -> str:
    parts = Path(relative_path).parts
    if len(parts) >= 2 and parts[0] == "personas":
        return normalize_persona_id(parts[1])
    return "global"


def is_persona_core_relative_path(relative_path: str) -> bool:
    parts = Path(relative_path).parts
    return (
        len(parts) == 3
        and parts[0] == "personas"
        and parts[2] in PERSONA_CORE_FILENAMES
    )


def _build_default_persona_summary(project_id: str = "default") -> dict[str, Any]:
    core_docs = workspace.get_core_documents(project_id)
    soul_path = core_docs["soul"]
    return _build_persona_summary(
        "default",
        soul_path,
        is_default=True,
        label=DEFAULT_PERSONA_LABEL,
        project_id=project_id,
    )


def _require_text(value: str | None, field_name: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError(f"{field_name} 不可為空")
    return text


def _build_persona_summary(
    persona_id: str,
    soul_path: Path,
    *,
    is_default: bool,
    label: str = "",
    project_id: str = "default",
) -> dict[str, Any]:
    ws = workspace.get_workspace_root(project_id)
    meta = _read_avatar_meta(persona_id, project_id, is_default=is_default)
    return {
        "persona_id": persona_id,
        "label": label or extract_heading_or_name(soul_path, persona_id),
        "path": soul_path.relative_to(ws).as_posix(),
        "preview": _read_preview(soul_path),
        "is_default": is_default,
        "avatar_char_id": meta.get("avatar_char_id"),
    }


def _read_avatar_meta(persona_id: str, project_id: str, *, is_default: bool) -> dict[str, Any]:
    meta_path = _avatar_meta_path(persona_id, project_id, is_default=is_default)
    if not meta_path.exists():
        return {}
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def set_persona_avatar(
    persona_id: str,
    char_id: str | None,
    project_id: str = "default",
) -> dict[str, Any]:
    normalized = normalize_persona_id(persona_id)
    if normalized == "default":
        ws = workspace.get_workspace_root(project_id)
        ws.mkdir(parents=True, exist_ok=True)
    else:
        persona_dir = get_persona_directory(normalized, project_id)
        if not (persona_dir / "SOUL.md").exists():
            raise ValueError("persona 不存在")

    is_default = normalized == "default"
    meta_path = _avatar_meta_path(normalized, project_id, is_default=is_default)
    meta = _read_avatar_meta(normalized, project_id, is_default=is_default)

    cleaned_char_id = char_id.strip() if (char_id and char_id.strip()) else None
    meta["avatar_char_id"] = cleaned_char_id

    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return {
        "status": "ok",
        "persona_id": normalized,
        "avatar_char_id": cleaned_char_id,
    }


GREETING_LANGUAGES = ("zh", "en", "es", "ja", "ko")
GREETING_MAX_CHARS = 500
VOICE_ID_MAX_CHARS = 128
_VOICE_ID_RE = re.compile(r"[A-Za-z0-9._:-]+")


class PersonaNotFoundError(ValueError):
    """The persona has no workspace folder (route answers 404, not 400)."""


def _existing_persona_meta(persona_id: str, project_id: str) -> tuple[str, Path, dict[str, Any]]:
    normalized = normalize_persona_id(persona_id)
    is_default = normalized == "default"
    if not is_default and not (get_persona_directory(normalized, project_id) / "SOUL.md").exists():
        raise PersonaNotFoundError("persona 不存在")
    meta_path = _avatar_meta_path(normalized, project_id, is_default=is_default)
    return normalized, meta_path, _read_avatar_meta(normalized, project_id, is_default=is_default)


def _stored_map(meta: dict[str, Any], key: str) -> dict[str, str]:
    value = meta.get(key)
    if not isinstance(value, dict):
        return {}
    return {
        lang: text for lang, text in value.items()
        if lang in GREETING_LANGUAGES and isinstance(text, str) and text
    }


def _validated_greetings(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ValueError("開場白格式不正確，必須是「語言: 文字」的對照。")
    result: dict[str, str] = {}
    for lang, text in raw.items():
        if lang not in GREETING_LANGUAGES:
            raise ValueError(f"開場白的語言只能是 {', '.join(GREETING_LANGUAGES)}。")
        if not isinstance(text, str):
            raise ValueError("開場白必須是文字。")
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("開場白不可以是空白。")
        if len(cleaned) > GREETING_MAX_CHARS:
            raise ValueError(f"開場白最多 {GREETING_MAX_CHARS} 個字。")
        result[lang] = cleaned
    return result


def _validated_voices(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ValueError("聲音格式不正確，必須是「語言: 聲音代號」的對照。")
    result: dict[str, str] = {}
    for lang, voice in raw.items():
        if lang not in GREETING_LANGUAGES:
            raise ValueError(f"聲音的語言只能是 {', '.join(GREETING_LANGUAGES)}。")
        if not isinstance(voice, str) or not voice or len(voice) > VOICE_ID_MAX_CHARS:
            raise ValueError(f"聲音代號必須是 1 到 {VOICE_ID_MAX_CHARS} 個字元。")
        if not _VOICE_ID_RE.fullmatch(voice):
            raise ValueError("聲音代號只能用英數字與 . _ : - 這幾個符號。")
        result[lang] = voice
    return result


def get_persona_language_settings(persona_id: str, project_id: str = "default") -> dict[str, Any]:
    normalized, _, meta = _existing_persona_meta(persona_id, project_id)
    return {
        "persona_id": normalized,
        "greetings": _stored_map(meta, "greetings"),
        "voices": _stored_map(meta, "voices"),
    }


def set_persona_language_settings(
    persona_id: str,
    greetings: Any,
    voices: Any,
    project_id: str = "default",
) -> dict[str, Any]:
    """Replace the persona's per-language greetings and voices, keeping other meta fields."""
    cleaned_greetings = _validated_greetings(greetings)
    cleaned_voices = _validated_voices(voices)
    normalized, meta_path, meta = _existing_persona_meta(persona_id, project_id)
    if normalized == "default":
        meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta["greetings"] = cleaned_greetings
    meta["voices"] = cleaned_voices
    workspace.write_text_atomic(meta_path, json.dumps(meta, ensure_ascii=False))
    return {"persona_id": normalized, "greetings": cleaned_greetings, "voices": cleaned_voices}


def get_persona_greeting(
    persona_id: str, language: str, project_id: str = "default",
) -> dict[str, Any] | None:
    """The greeting text and voice for *language*, or None when none is set."""
    settings = get_persona_language_settings(persona_id, project_id)
    text = settings["greetings"].get(language)
    if not text:
        return None
    return {"language": language, "text": text, "voice": settings["voices"].get(language)}


# QA 圖片上傳產生的代號：uuid 加副檔名。只收這種，人設不能指到工作區裡的任意檔案。
_CONTACT_IMAGE_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(png|jpe?g|webp|gif|bmp|avif)"
)


def set_persona_contact_image(
    persona_id: str, image_id: str | None, project_id: str = "default",
) -> dict[str, Any]:
    """Attach (or clear with None) the image every reply of this persona carries, such as a QR code."""
    from knowledge.qa_images import resolve_qa_image_path

    normalized, meta_path, meta = _existing_persona_meta(persona_id, project_id)
    if image_id is None:
        meta.pop("contact_image_id", None)
    else:
        if not _CONTACT_IMAGE_RE.fullmatch(image_id):
            raise ValueError("聯絡圖片必須是 QA 圖片上傳後拿到的圖片代號。")
        if resolve_qa_image_path(image_id, project_id) is None:
            raise ValueError("找不到這張圖片，請先上傳到 QA 圖片。")
        meta["contact_image_id"] = image_id
    if normalized == "default":
        meta_path.parent.mkdir(parents=True, exist_ok=True)
    workspace.write_text_atomic(meta_path, json.dumps(meta, ensure_ascii=False))
    return {"persona_id": normalized, "contact_image_id": meta.get("contact_image_id")}


def persona_contact_image(persona_id: str, project_id: str = "default") -> str | None:
    """The persona's contact image id, or None; never raises (it runs on every chat reply)."""
    try:
        _, _, meta = _existing_persona_meta(persona_id, project_id)
    except ValueError:
        return None
    value = meta.get("contact_image_id")
    return value if isinstance(value, str) and _CONTACT_IMAGE_RE.fullmatch(value) else None


def persona_contact_image_ids(project_id: str = "default") -> set[str]:
    """Contact images of every persona in the project, so image cleanup keeps them."""
    ids = set()
    for persona in list_personas(project_id):
        if image_id := persona_contact_image(persona["persona_id"], project_id):
            ids.add(image_id)
    return ids


def _avatar_meta_path(persona_id: str, project_id: str, *, is_default: bool) -> Path:
    if is_default:
        return workspace.get_workspace_root(project_id) / AVATAR_META_FILENAME
    return get_persona_directory(persona_id, project_id) / AVATAR_META_FILENAME


def _build_persona_files(label: str) -> dict[str, str]:
    return {
        filename: _PERSONA_TEMPLATES[key](label)
        for key, filename in PERSONA_CORE_KEYS_TO_FILES.items()
    }


def extract_heading_or_name(path: Path, fallback: str) -> str:
    """Extract the first heading text from a markdown file, or return fallback."""
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            if heading:
                return heading
    return fallback


def _read_preview(path: Path, limit: int = 120) -> str:
    snippet = " ".join(path.read_text(encoding="utf-8-sig").split())
    return snippet[:limit]


def _simple_persona_template(section: str, description: str) -> callable:
    """Return a template builder for a standard persona override section."""
    def builder(label: str) -> str:
        return (
            f"# {label} Persona {section}\n\n"
            f"- {description}\n"
            f"- 若沒有特別覆蓋，系統仍會沿用全域 {section} 設定。\n"
        )
    return builder


_PERSONA_TEMPLATES: dict[str, callable] = {
    "soul": lambda label: f"""# {label} Persona SOUL

## 角色設定

你是「{label}」這個 persona 的對話核心。
- 這個 persona 會覆蓋預設的 SOUL 設定。
- 保留 openVman Brain 的誠實與可執行回覆原則。

## 回應風格

- 先說重點，再補充必要細節。
- 若資訊不足，直接指出缺口，不要編造。
""",
    "agents": _simple_persona_template(
        "AGENTS", "在這裡定義 persona 專屬的工作流程或轉派規則。",
    ),
    "tools": _simple_persona_template(
        "TOOLS", "在這裡記錄 persona 專屬工具、參數限制或使用規範。",
    ),
    "memory": _simple_persona_template(
        "MEMORY", "在這裡記錄 persona 的長期核心記憶或固定事實。",
    ),
    "identity": lambda label: f"""# {label} Persona IDENTITY

## 基本資訊
- name: {label}
- theme: default

## 說明
- 此檔定義 {label} persona 的外部身份與視覺主題。
- 若沒有特別覆蓋，系統仍會沿用全域 IDENTITY 設定。
""",
}

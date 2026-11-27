from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict

from knowledge.workspace import (
    GUARDRAILS_FILENAME,
    GUARDRAILS_MAX_CHARS,
    GUARDRAILS_TEMPLATE,
    content_hash,
    document_save_lock,
    ensure_workspace_scaffold,
    get_workspace_root,
    guardrails_link_problem,
    resolve_workspace_document,
    saved_content_hash,
    write_text_atomic,
)
from personas.personas import (
    clone_persona_scaffold,
    create_persona_scaffold,
    delete_persona_scaffold,
    PersonaNotFoundError,
    get_persona_greeting,
    get_persona_language_settings,
    list_personas,
    normalize_persona_id,
    persona_label,
    set_persona_avatar,
    set_persona_label,
    set_persona_language_settings,
)
from protocol.schemas import (
    PersonaAvatarRequest,
    PersonaCloneRequest,
    PersonaCreateRequest,
    PersonaDeleteRequest,
)
from safety.internal_auth import PROJECT_ID_HEADER, require_internal_token
from safety.observability import log_event
from safety.vendor_access import (
    VENDOR_PERSONA_DOCUMENTS,
    VendorRequest,
    vendor_workspace_path,
)

router = APIRouter(
    prefix="/brain",
    tags=["Personas"],
    dependencies=[Depends(require_internal_token)],
)


@router.get("/personas", summary="列出人設清單")
async def list_personas_route(project_id: str = "default", vendor: VendorRequest = False):
    items = _list_vendor_personas(project_id) if vendor else list_personas(project_id)
    return {"personas": items, "persona_count": len(items)}


def _persona_relative(persona_id: str, filename: str) -> str:
    try:
        persona_id = normalize_persona_id(persona_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="角色代號格式不正確。") from exc
    prefix = "" if persona_id == "default" else f"personas/{persona_id}/"
    return f"{prefix}{filename}"


def _is_persona_document(relative: str) -> bool:
    parts = Path(relative).parts
    return (len(parts) == 1 and parts[0] in VENDOR_PERSONA_DOCUMENTS) or (
        len(parts) == 3 and parts[0] == "personas" and parts[2] in VENDOR_PERSONA_DOCUMENTS
    )


def _locate(project_id: str, relative: str, vendor: bool) -> Path:
    """Resolve a persona document path for this caller.

    廠商請求不接受任何別名（符號連結、硬連結）。內部帳號照一般工作區規則解析，但解析
    後仍必須是某個角色的 SOUL.md／AGENTS.md：Backend 只查了「改知識庫與人設」，不能經由
    連結寫到保護規則或記憶。
    """
    if vendor:
        return vendor_workspace_path(project_id, relative, "persona")
    try:
        path = resolve_workspace_document(relative, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="沒有權限使用這個功能。") from exc
    root = get_workspace_root(project_id).resolve()
    if not _is_persona_document(path.relative_to(root).as_posix()):
        raise HTTPException(status_code=403, detail="沒有權限使用這個功能。")
    return path


def _persona_document_path(
    persona_id: str,
    project_id: str,
    filename: str = "SOUL.md",
    *,
    create: bool = False,
    vendor: bool = True,
) -> Path:
    """Locate a persona's SOUL.md or AGENTS.md.

    非預設角色一定要有自己的 SOUL.md（清單才列得出來）；只剩 AGENTS.md 的孤立資料夾
    讀寫都擋。``create`` 讓存檔替已存在的角色建立它自己的 AGENTS.md。
    """
    relative = _persona_relative(persona_id, filename)
    if filename != "SOUL.md":
        soul = _locate(project_id, _persona_relative(persona_id, "SOUL.md"), vendor)
        if not soul.is_file():
            raise HTTPException(status_code=404, detail="找不到角色的人設內容。")
    path = _locate(project_id, relative, vendor)
    if path.is_file() or (create and filename != "SOUL.md"):
        return path
    raise HTTPException(status_code=404, detail="找不到角色的人設內容。")


def _persona_soul_path(persona_id: str, project_id: str, vendor: bool = True) -> Path:
    return _persona_document_path(persona_id, project_id, vendor=vendor)


def _list_vendor_personas(project_id: str) -> list[dict]:
    root = get_workspace_root(project_id).resolve()
    personas_root = root / "personas"
    directories = personas_root.iterdir() if personas_root.is_dir() and not personas_root.is_symlink() else ()
    items = []
    for persona_id in ("default", *sorted(path.name for path in directories if path.name != "default")):
        try:
            if persona_id != normalize_persona_id(persona_id):
                continue
            _persona_soul_path(persona_id, project_id)
            label = persona_label(persona_id, project_id)
        except (HTTPException, OSError, ValueError):
            continue
        items.append({
            "persona_id": persona_id,
            "label": label,
            "is_default": persona_id == "default",
        })
    return items


class PersonaDocumentPut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = "default"
    persona_id: str = "default"
    content: str
    # GET 回的 content_hash；帶了就檢查檔案在載入後沒被別人改過，舊畫面不會整份蓋掉新內容。
    # 檔案還不存在時以空字串的雜湊為準，兩個人同時新建也只有先存的成功。
    base_hash: str | None = None


STALE_DOCUMENT_DETAIL = "這份文件在你編輯時被改過了，請重新載入後再存檔"


def _read_document(path: Path) -> dict[str, str]:
    content = path.read_text(encoding="utf-8-sig")
    return {"content": content, "content_hash": content_hash(content)}


def _write_document(path: Path, payload: PersonaDocumentPut) -> dict[str, str]:
    # 和工作區文件 API 共用的跨行程鎖（原始文件模式也存同一份檔案）：比對到寫入之間
    # 不能被別的存檔插隊。沒帶 base_hash 的舊呼叫方式也進鎖，才不會插進別人的比對與寫入之間。
    with document_save_lock(payload.project_id):
        if payload.base_hash:
            try:
                current = path.read_text(encoding="utf-8-sig")
            except FileNotFoundError:
                current = ""
            if content_hash(current) != payload.base_hash:
                raise HTTPException(status_code=409, detail=STALE_DOCUMENT_DETAIL)
        write_text_atomic(path, payload.content)
    return {"status": "ok", "content_hash": saved_content_hash(payload.content)}


@router.get("/personas/soul", summary="讀取角色的 SOUL.md")
def get_persona_soul(
    persona_id: str = "default", project_id: str = "default", vendor: VendorRequest = False,
):
    return _read_document(_persona_soul_path(persona_id, project_id, vendor))


@router.put("/personas/soul", summary="儲存角色的 SOUL.md")
def put_persona_soul(payload: PersonaDocumentPut, vendor: VendorRequest = False):
    path = _persona_soul_path(payload.persona_id, payload.project_id, vendor)
    return _write_document(path, payload)


@router.get("/personas/agents", summary="讀取角色的 AGENTS.md")
def get_persona_agents(
    persona_id: str = "default", project_id: str = "default", vendor: VendorRequest = False,
):
    return _read_document(_persona_document_path(persona_id, project_id, "AGENTS.md", vendor=vendor))


@router.put("/personas/agents", summary="儲存角色的 AGENTS.md")
def put_persona_agents(payload: PersonaDocumentPut, vendor: VendorRequest = False):
    path = _persona_document_path(
        payload.persona_id, payload.project_id, "AGENTS.md", create=True, vendor=vendor,
    )
    return _write_document(path, payload)


@router.get("/personas/guardrails", summary="讀取專案的保護規則（唯讀）")
def get_persona_guardrails(project_id: str = "default"):
    # 只有讀取：寫入走工作區文件 API，需要「改其他設定」。
    root = ensure_workspace_scaffold(project_id)
    # 和提示詞同一套判斷：檔案是連結就視為沒設定（linked 讓後台說明原因，不提供帶入範本）。
    linked = guardrails_link_problem(project_id)
    path = root / GUARDRAILS_FILENAME
    try:
        content = "" if linked or not path.is_file() else path.read_text(encoding="utf-8-sig")
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="保護規則的檔案讀不出來，請技術人員檢查檔案內容。") from exc
    # 沒設定時 content 為空字串；template 給有權限的內部帳號一鍵帶入建議內容。
    # content_hash 與工作區文件 API 相同，存檔時帶回，舊畫面不會蓋掉較新的內容；
    # 檔案還不存在時是空字串的雜湊，兩個人同時第一次建立也只有先存的成功。連結不能存，給空字串。
    return {
        "content": content,
        "template": GUARDRAILS_TEMPLATE,
        "linked": linked,
        "max_chars": GUARDRAILS_MAX_CHARS,
        "content_hash": "" if linked else content_hash(content),
    }


@router.post("/personas", summary="建立新人設")
async def create_persona_route(payload: PersonaCreateRequest):
    try:
        result = create_persona_scaffold(
            payload.persona_id,
            payload.label,
            payload.project_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_event("persona_created", persona_id=payload.persona_id, project_id=payload.project_id)
    return result


@router.delete("/personas", summary="刪除人設")
async def delete_persona_route(payload: PersonaDeleteRequest):
    try:
        result = delete_persona_scaffold(payload.persona_id, payload.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_event("persona_deleted", persona_id=payload.persona_id, project_id=payload.project_id)
    return result


@router.post("/personas/clone", summary="複製人設")
async def clone_persona_route(payload: PersonaCloneRequest):
    try:
        result = clone_persona_scaffold(
            payload.source_persona_id,
            payload.target_persona_id,
            payload.project_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_event(
        "persona_cloned",
        source_persona_id=payload.source_persona_id,
        target_persona_id=payload.target_persona_id,
        project_id=payload.project_id,
    )
    return result


@router.post("/personas/avatar", summary="綁定 persona 的 Avatar 角色")
async def set_persona_avatar_route(payload: PersonaAvatarRequest):
    try:
        result = set_persona_avatar(
            payload.persona_id,
            payload.avatar_char_id,
            payload.project_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_event(
        "persona_avatar_set",
        persona_id=payload.persona_id,
        avatar_char_id=payload.avatar_char_id,
        project_id=payload.project_id,
    )
    return result


class PersonaLanguageSettingsPut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona_id: str
    project_id: str = "default"
    greetings: Any
    voices: Any


def _language_settings_error(exc: ValueError) -> HTTPException:
    # 找不到人設是 404；其餘（代號、語言、字數、聲音代號不合法）是 400，訊息本身就是白話。
    status = 404 if isinstance(exc, PersonaNotFoundError) else 400
    return HTTPException(status_code=status, detail=str(exc))


@router.get("/personas/language-settings", summary="讀取人設各語言的開場白與聲音")
def get_persona_language_settings_route(persona_id: str = "default", project_id: str = "default"):
    try:
        return get_persona_language_settings(persona_id, project_id)
    except ValueError as exc:
        raise _language_settings_error(exc) from exc


@router.put("/personas/language-settings", summary="整份取代人設各語言的開場白與聲音")
def put_persona_language_settings_route(payload: PersonaLanguageSettingsPut):
    try:
        result = set_persona_language_settings(
            payload.persona_id, payload.greetings, payload.voices, payload.project_id,
        )
    except ValueError as exc:
        raise _language_settings_error(exc) from exc
    log_event(
        "persona_language_settings_set",
        persona_id=result["persona_id"],
        project_id=payload.project_id,
        greeting_languages=sorted(result["greetings"]),
        voice_languages=sorted(result["voices"]),
    )
    return result


@router.get("/personas/greeting", summary="取得某語言的開場白與聲音")
def get_persona_greeting_route(
    language: str,
    persona_id: str = "default",
    project_id: str | None = None,
    trusted_project_id: str = Header("", alias=PROJECT_ID_HEADER),
):
    # Backend 依登入身分或嵌入金鑰算出的專案放在標頭，以它為準；網址沒帶專案時不能
    # 退回 default，否則嵌入金鑰的頁面會讀到別的專案的開場白。
    if trusted_project_id and project_id and trusted_project_id != project_id:
        raise HTTPException(status_code=400, detail="project_id 跟登入的專案不一致。")
    project_id = trusted_project_id or project_id or "default"
    try:
        greeting = get_persona_greeting(persona_id, language, project_id)
    except ValueError as exc:
        raise _language_settings_error(exc) from exc
    if greeting is None:
        raise HTTPException(status_code=404, detail="這個語言沒有設定開場白。")
    return greeting


class PersonaLabelPut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona_id: str
    project_id: str = "default"
    label: str


@router.put("/personas/label", summary="修改人設的顯示名稱（預設人設也可以）")
def put_persona_label_route(payload: PersonaLabelPut):
    try:
        result = set_persona_label(payload.persona_id, payload.label, payload.project_id)
    except ValueError as exc:
        raise _language_settings_error(exc) from exc
    log_event("persona_label_set", persona_id=result["persona_id"], project_id=payload.project_id)
    return result

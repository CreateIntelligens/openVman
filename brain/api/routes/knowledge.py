from __future__ import annotations

import asyncio
import json
from typing import Any


from fastapi import APIRouter, File, Form, HTTPException, UploadFile, Response
from fastapi.responses import HTMLResponse

from core.chat_service import record_generation_failure
from knowledge.doc_meta import get_document_meta
from knowledge.graph import (
    GRAPH_SUBDIR,
    EmptyGraphError,
    load_project_graph,
    load_project_status,
    load_project_summary,
    rebuild_project_graph,
)
from knowledge.indexer import (
    has_stale_documents,
    rebuild_knowledge_index,
    rename_document_records,
)
from knowledge.knowledge_admin import (
    apply_workspace_document_normalization,
    commit_raw_documents,
    create_workspace_directory,
    delete_workspace_directory,
    delete_workspace_document,
    list_knowledge_base_directories,
    list_knowledge_base_documents,
    list_qa_entries,
    list_raw_files,
    list_workspace_documents,
    move_workspace_document,
    preview_workspace_document_normalization,
    read_workspace_document,
    renormalize_workspace_document,
    save_uploaded_artifact,
    save_uploaded_document,
    save_workspace_document,
    save_workspace_note,
    update_workspace_document_meta,
)
from knowledge import commit_jobs
from knowledge.workspace import get_workspace_root
from protocol.schemas import (
    AdminActionRequest,
    KnowledgeDocumentActionRequest,
    KnowledgeDocumentMetaPatchRequest,
    KnowledgeDocumentMoveRequest,
    KnowledgeDocumentPutRequest,
    KnowledgeNoteCreateRequest,
)
from safety.observability import log_event, log_exception

router = APIRouter(prefix="/brain", tags=["Knowledge"])


_REINDEX_DEBOUNCE_SECONDS = 2.0
_reindex_state: dict[str, dict[str, Any]] = {}


def _schedule_reindex(project_id: str) -> None:
    """Coalesce reindex requests: debounce rapid edits, never run two at once."""
    state = _reindex_state.setdefault(project_id, {"task": None, "dirty": False})
    state["dirty"] = True
    task = state["task"]
    if task is not None and not task.done():
        return
    state["task"] = asyncio.create_task(_reindex_worker(project_id, state))


async def _reindex_worker(project_id: str, state: dict[str, Any]) -> None:
    while state["dirty"]:
        await asyncio.sleep(_REINDEX_DEBOUNCE_SECONDS)
        state["dirty"] = False
        try:
            result = await asyncio.to_thread(rebuild_knowledge_index, project_id)
        except Exception as exc:
            log_exception("knowledge_reindex_auto_error", exc, project_id=project_id)
            continue
        log_event("knowledge_reindex_auto", project_id=project_id, **result)
    _schedule_graph_rebuild(project_id)



async def _background_rename_document(source_path: str, target_path: str, project_id: str) -> None:
    try:
        await asyncio.to_thread(rename_document_records, source_path, target_path, project_id)
    except Exception as exc:
        log_exception("knowledge_rename_auto_error", exc, project_id=project_id)
        return
    log_event(
        "knowledge_rename_auto",
        project_id=project_id,
        source_path=source_path,
        target_path=target_path,
    )


@router.get("/knowledge/documents", summary="取得工作區所有文件")
async def list_knowledge_documents_route(project_id: str = "default"):
    documents = list_workspace_documents(project_id)
    return {"documents": documents, "document_count": len(documents)}


@router.get("/knowledge/base/documents", summary="取得知識庫樹狀結構")
async def list_knowledge_base_documents_route(project_id: str = "default"):
    documents = list_knowledge_base_documents(project_id)
    directories = list_knowledge_base_directories(project_id)
    return {
        "documents": documents,
        "document_count": len(documents),
        "directories": directories,
    }


def _assert_not_qa_document(path: str, project_id: str) -> None:
    """Block LLM-renormalization on QA files to prevent corrupting their structure."""
    if get_document_meta(path, project_id).get("source_type") == "qa":
        raise HTTPException(status_code=400, detail="QA 知識文件不支援重新整理，以免破壞問答格式結構")



@router.get("/knowledge/qa", summary="取得所有已啟用 QA 來源的問答清單")
async def list_knowledge_qa_route(project_id: str = "default"):
    entries = list_qa_entries(project_id)
    return {"entries": entries, "count": len(entries)}


@router.get("/knowledge/document", summary="讀取單一知識文件")
async def get_knowledge_document_route(path: str, project_id: str = "default"):
    try:
        return read_workspace_document(path, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="找不到指定文件") from exc


@router.put("/knowledge/document", summary="儲存知識文件")
async def save_knowledge_document_route(payload: KnowledgeDocumentPutRequest):
    try:
        document = save_workspace_document(payload.path, payload.content, payload.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # QA 文件允許在文件頁編輯：儲存後把掛載中節點的條目同步成檔案現況，
    # 取代先前直接 400 擋下的作法（移動/刪除仍受 guard 保護）。
    if get_document_meta(payload.path, payload.project_id).get("source_type") == "qa":
        from knowledge.qa_nodes import sync_entries_for_source

        sync_entries_for_source(payload.path, payload.project_id)
    _schedule_reindex(payload.project_id)
    return {"status": "ok", "document": document}


@router.patch("/knowledge/document/meta", summary="更新文件中繼屬性")
async def patch_knowledge_document_meta_route(payload: KnowledgeDocumentMetaPatchRequest):
    try:
        document = update_workspace_document_meta(
            payload.path,
            payload.project_id,
            enabled=payload.enabled,
            source_type=payload.source_type,
            source_url=payload.source_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "status": "ok",
        "path": document["path"],
        "enabled": document["enabled"],
        "source_type": document["source_type"],
        "source_url": document["source_url"],
    }


@router.delete("/knowledge/document", summary="刪除知識文件")
async def delete_knowledge_document_route(path: str, project_id: str = "default"):
    if get_document_meta(path, project_id).get("source_type") == "qa":
        from knowledge.qa_nodes import remove_entries_for_source
        remove_entries_for_source(path, project_id)
    try:
        delete_workspace_document(path, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="找不到指定文件") from exc
    _schedule_reindex(project_id)
    return {"status": "ok"}


@router.post("/knowledge/move", summary="移動/重新命名知識文件")
async def move_knowledge_document_route(payload: KnowledgeDocumentMoveRequest):
    if get_document_meta(payload.source_path, payload.project_id).get("source_type") == "qa":
        from knowledge.qa_nodes import rename_source_path_in_nodes
        rename_source_path_in_nodes(payload.source_path, payload.target_path, payload.project_id)
    try:
        document = move_workspace_document(payload.source_path, payload.target_path, payload.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    asyncio.create_task(
        _background_rename_document(payload.source_path, payload.target_path, payload.project_id)
    )
    return {"status": "ok", "document": document}


@router.post("/knowledge/directory", summary="建立資料夾")
async def create_knowledge_directory_route(payload: KnowledgeDocumentPutRequest):
    try:
        return create_workspace_directory(payload.path, payload.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/knowledge/directory", summary="刪除資料夾")
async def delete_knowledge_directory_route(path: str, project_id: str = "default"):
    try:
        return delete_workspace_directory(path, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/knowledge/raw/upload", summary="上傳原始檔案至 raw 區")
async def upload_knowledge_raw_documents_route(
    files: list[UploadFile] = File(...),
    target_dir: str = Form("raw"),
    project_id: str = Form("default"),
    relative_paths: list[str] = Form(default_factory=list),
):
    uploaded: list[dict[str, object]] = []
    try:
        for index, upload in enumerate(files):
            relative_path = (
                relative_paths[index] if index < len(relative_paths) else ""
            )
            uploaded.append(
                save_uploaded_artifact(
                    upload.filename or "",
                    await upload.read(),
                    target_dir,
                    project_id,
                    relative_path=relative_path,
                )
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "files": uploaded}


@router.post("/knowledge/renormalize/preview", summary="預覽既有知識文件整理結果")
async def preview_renormalize_knowledge_document_route(
    payload: KnowledgeDocumentActionRequest,
):
    pid = payload.project_id
    _assert_not_qa_document(payload.path, pid)
    try:
        document = await asyncio.to_thread(
            preview_workspace_document_normalization, payload.path, pid
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        log_exception("knowledge_renormalize_preview_error", exc, project_id=pid)
        raise HTTPException(status_code=500, detail="整理預覽失敗") from exc
    return {"status": "ok", "project_id": pid, **document}


@router.post("/knowledge/renormalize/apply", summary="套用預覽整理結果並重建索引與圖譜")
async def apply_renormalize_knowledge_document_route(
    payload: KnowledgeDocumentPutRequest,
):
    pid = payload.project_id
    _assert_not_qa_document(payload.path, pid)
    try:
        document = await asyncio.to_thread(
            apply_workspace_document_normalization, payload.path, payload.content, pid
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        log_exception("knowledge_renormalize_apply_error", exc, project_id=pid)
        raise HTTPException(status_code=500, detail="套用整理失敗") from exc

    log_event("knowledge_renormalize_apply", project_id=pid, path=payload.path)
    _schedule_reindex(pid)

    return {
        "status": "ok",
        "project_id": pid,
        "document": document,
        "indexed": "background",
        "graph": "building",
    }


@router.post("/knowledge/renormalize", summary="重新整理既有知識文件並重建索引與圖譜")
async def renormalize_knowledge_document_route(payload: KnowledgeDocumentActionRequest):
    """Re-run LLM normalization over an existing knowledge/ document (in place),
    then reindex and rebuild the graph so the cleaned content re-enters RAG.
    """
    pid = payload.project_id
    _assert_not_qa_document(payload.path, pid)
    try:
        document = await asyncio.to_thread(
            renormalize_workspace_document, payload.path, pid
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        log_exception("knowledge_renormalize_error", exc, project_id=pid)
        raise HTTPException(status_code=500, detail="整理失敗") from exc

    log_event("knowledge_renormalize", project_id=pid, path=payload.path)
    _schedule_reindex(pid)

    return {
        "status": "ok",
        "project_id": pid,
        "document": document,
        "indexed": "background",
        "graph": "building",
    }


@router.post("/knowledge/raw/commit", summary="採納 raw 區檔案進知識庫（背景執行，逐檔進度可查詢）", status_code=202)
async def commit_knowledge_raw_route(payload: AdminActionRequest, response: Response):
    """The 'commit' step: promote staged raw/ files into knowledge/ in the
    background (per-file LLM normalization is slow), then rebuild the vector
    index and concept graph. Progress is polled via /knowledge/raw/commit/status.
    """
    pid = payload.project_id
    pending = await asyncio.to_thread(list_raw_files, pid)
    if not pending:
        response.status_code = 200
        return {"status": "nothing_to_commit", "project_id": pid, "committed": [], "skipped": []}
    if not commit_jobs.start_job(pid, pending):
        response.status_code = 200
        return {"status": "already_running", "project_id": pid, "job": commit_jobs.job_snapshot(pid)}
    asyncio.create_task(_run_commit_job(pid))
    response.status_code = 202
    return {"status": "started", "project_id": pid, "job": commit_jobs.job_snapshot(pid)}


async def _run_commit_job(project_id: str) -> None:
    def _on_progress(path: str, state: str) -> None:
        commit_jobs.update_file(project_id, path, state)

    try:
        result = await asyncio.to_thread(commit_raw_documents, project_id, _on_progress)
    except Exception as exc:
        commit_jobs.fail_job(project_id, repr(exc))
        log_exception("knowledge_commit_error", exc, project_id=project_id)
        return
    commit_jobs.finish_job(project_id, result["committed"], result["skipped"])
    log_event("knowledge_commit", project_id=project_id, committed=len(result["committed"]))
    if result["committed"]:
        _schedule_reindex(project_id)


@router.get("/knowledge/raw/commit/status", summary="查詢採納進度")
async def commit_status_route(project_id: str = "default"):
    return commit_jobs.job_snapshot(project_id)



@router.post("/knowledge/upload", summary="上傳實體檔案至知識庫")
async def upload_knowledge_documents_route(
    files: list[UploadFile] = File(...),
    target_dir: str = Form(""),
    project_id: str = Form("default"),
    relative_paths: list[str] = Form(default_factory=list),
):
    uploaded: list[dict[str, object]] = []
    try:
        for index, upload in enumerate(files):
            relative_path = relative_paths[index] if index < len(relative_paths) else ""
            uploaded.append(
                save_uploaded_document(
                    upload.filename or "",
                    await upload.read(),
                    target_dir,
                    project_id,
                    relative_path=relative_path,
                )
            )
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="檔案需為 UTF-8 編碼") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _schedule_reindex(project_id)
    return {"status": "ok", "files": uploaded}


@router.post("/knowledge/note", summary="建立知識筆記")
async def create_knowledge_note_route(payload: KnowledgeNoteCreateRequest):
    try:
        document = save_workspace_note(
            payload.title,
            payload.content,
            payload.project_id,
            payload.target_dir,
            note_format=payload.note_format,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _schedule_reindex(payload.project_id)
    return {"status": "ok", "document": document, "path": document["path"], "size": document["size"]}


@router.post("/knowledge/reindex", summary="重整全域知識索引")
async def reindex_knowledge_route(payload: AdminActionRequest):
    try:
        result = await asyncio.to_thread(rebuild_knowledge_index, payload.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        log_exception("knowledge_reindex_error", exc)
        record_generation_failure("reindex", "index_failure", str(exc))
        raise HTTPException(status_code=500, detail="知識重建失敗") from exc
    log_event("knowledge_reindex", project_id=payload.project_id, **result)
    return result


_graph_inflight: dict[str, asyncio.Task] = {}


def _schedule_graph_rebuild(project_id: str) -> bool:
    """Start a background graph rebuild unless one is already in flight.

    Returns True if a new rebuild was scheduled, False if an existing one is
    still running (callers can surface "already_building" to the client).
    """
    existing = _graph_inflight.get(project_id)
    if existing and not existing.done():
        return False
    task = asyncio.create_task(_run_graph_rebuild(project_id))
    _graph_inflight[project_id] = task
    return True


def _write_empty_graph_outputs(
    project_id: str,
    started_at: str,
    built_at: str,
    write_status,
) -> None:
    out_dir = get_workspace_root(project_id) / GRAPH_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "graph.json").write_text(
        json.dumps({"nodes": [], "edges": []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "graph.html").write_text(
        "<html><body><p style='font-family: sans-serif; text-align: center; "
        "margin-top: 100px; color: #64748b;'>此項目尚無知識圖譜資料</p></body></html>",
        encoding="utf-8",
    )
    summary = {
        "project_id": project_id,
        "built_at": built_at,
        "note_graph_files": [],
        "nodes": 0,
        "edges": 0,
        "communities": 0,
        "god_nodes": [],
        "surprising_bridges": 0,
        "ast_nodes": 0,
        "semantic_nodes": 0,
        "cohesion": {},
        "harness": {},
        "output_dir": str(out_dir),
        "obsidian_dir": str(out_dir / "obsidian"),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_status(
        project_id,
        {
            "state": "ready",
            "project_id": project_id,
            "started_at": started_at,
            "finished_at": built_at,
            "nodes": 0,
            "edges": 0,
            "communities": 0,
        },
    )


async def _run_graph_rebuild(project_id: str) -> None:
    from datetime import datetime, timezone

    from knowledge.graph import _write_status  # re-export internal helper

    started_at = datetime.now(timezone.utc).isoformat()
    _write_status(project_id, {"state": "building", "project_id": project_id, "started_at": started_at})
    try:
        # Never build the graph on top of a stale embedding index: graph
        # expansion fetches neighbour files' chunks from the vector store, so an
        # index lagging the files would let the graph point at content that
        # can't be retrieved. Reindex first (incremental, near-noop if current).
        if await asyncio.to_thread(has_stale_documents, project_id):
            await asyncio.to_thread(rebuild_knowledge_index, project_id)
            log_event("knowledge_reindex_before_graph", project_id=project_id)
        summary = await asyncio.to_thread(rebuild_project_graph, project_id)
    except FileNotFoundError as exc:
        _write_status(project_id, {"state": "failed", "project_id": project_id, "error": str(exc), "started_at": started_at})
        log_exception("knowledge_graph_rebuild_error", exc, project_id=project_id)
        return
    except EmptyGraphError:
        _write_empty_graph_outputs(
            project_id,
            started_at,
            datetime.now(timezone.utc).isoformat(),
            _write_status,
        )
        log_event("knowledge_graph_rebuild_empty", project_id=project_id)
        return
    except Exception as exc:  # pragma: no cover
        _write_status(project_id, {"state": "failed", "project_id": project_id, "error": repr(exc), "started_at": started_at})
        log_exception("knowledge_graph_rebuild_error", exc, project_id=project_id)
        return
    _write_status(
        project_id,
        {
            "state": "ready",
            "project_id": project_id,
            "started_at": started_at,
            "finished_at": summary.get("built_at"),
            "nodes": summary["nodes"],
            "edges": summary["edges"],
            "communities": summary["communities"],
        },
    )
    log_event(
        "knowledge_graph_rebuild",
        project_id=project_id,
        nodes=summary["nodes"],
        edges=summary["edges"],
        communities=summary["communities"],
    )


@router.post("/knowledge/graph/rebuild", summary="在背景重建專案知識圖譜", status_code=202)
async def rebuild_knowledge_graph_route(payload: AdminActionRequest):
    pid = payload.project_id
    if not _schedule_graph_rebuild(pid):
        return {"status": "already_building", "project_id": pid}
    return {"status": "building", "project_id": pid}


@router.get("/knowledge/graph/status", summary="查詢圖譜建置狀態")
async def graph_status_route(project_id: str = "default"):
    return load_project_status(project_id)


@router.get("/knowledge/graph/summary", summary="取得專案圖譜摘要")
async def graph_summary_route(project_id: str = "default"):
    try:
        return load_project_summary(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/knowledge/graph", summary="取得專案圖譜原始 JSON")
async def graph_json_route(project_id: str = "default"):
    try:
        return load_project_graph(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


_GRAPH_HTML_OVERRIDES = """
<style>
  #sidebar {
    position: absolute; top: 0; right: 0; height: 100%;
    max-width: min(320px, 85vw);
    transform: translateX(calc(100% - 32px));
    transition: transform .2s ease;
    z-index: 10;
  }
  #sidebar:hover, #sidebar:focus-within, #sidebar.open { transform: translateX(0); }
  #sidebar-toggle {
    position: absolute; top: 50%; left: -30px; transform: translateY(-50%);
    width: 30px; height: 60px;
    background: rgba(30,30,30,.85); color: #fff; border: 0;
    border-radius: 6px 0 0 6px; cursor: pointer; font-size: 14px;
  }
  @media (max-width: 640px) {
    #sidebar { max-width: 90vw; }
  }
</style>
<script>
  window.addEventListener('DOMContentLoaded', () => {
    const sb = document.getElementById('sidebar');
    if (!sb) return;
    const btn = document.createElement('button');
    btn.id = 'sidebar-toggle';
    btn.textContent = '‹';
    btn.title = '展開/收合側邊欄';
    btn.addEventListener('click', () => {
      sb.classList.toggle('open');
      btn.textContent = sb.classList.contains('open') ? '›' : '‹';
    });
    sb.appendChild(btn);
  });
</script>
"""


@router.get("/knowledge/graph/html", summary="取得專案圖譜 HTML 視覺化頁面")
async def graph_html_route(project_id: str = "default"):
    path = get_workspace_root(project_id) / GRAPH_SUBDIR / "graph.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="graph 尚未建立，請先呼叫 rebuild")
    html = path.read_text(encoding="utf-8")
    if "</body>" in html:
        html = html.replace("</body>", f"{_GRAPH_HTML_OVERRIDES}</body>", 1)
    else:
        html += _GRAPH_HTML_OVERRIDES
    return HTMLResponse(html)

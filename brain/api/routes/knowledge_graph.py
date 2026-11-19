"""Project knowledge graph: background rebuild, status, summary, JSON and HTML views."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from knowledge.graph import (
    GRAPH_SUBDIR,
    EmptyGraphError,
    load_project_graph,
    load_project_status,
    load_project_summary,
    rebuild_project_graph,
)
from knowledge.indexer import has_stale_documents, rebuild_knowledge_index
from knowledge.workspace import get_workspace_root
from protocol.schemas import AdminActionRequest
from safety.internal_auth import require_internal_token
from safety.observability import log_event, log_exception

router = APIRouter(
    prefix="/brain",
    tags=["Knowledge"],
    dependencies=[Depends(require_internal_token)],
)


_graph_inflight: dict[str, asyncio.Task] = {}


def schedule_graph_rebuild(project_id: str) -> bool:
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
    if not schedule_graph_rebuild(pid):
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

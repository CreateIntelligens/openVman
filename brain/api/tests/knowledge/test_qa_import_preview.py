"""Behavior tests for QA upload preview and commit decisions."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import knowledge.normalizer  # noqa: E402
import knowledge.qa_nodes as qa_nodes  # noqa: E402
import knowledge.workspace  # noqa: E402
from knowledge.qa_import_preview import preview_raw_documents  # noqa: E402
from knowledge.raw_import import commit_raw_documents  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture
def workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    monkeypatch.setattr(
        knowledge.workspace, "get_workspace_root", lambda project_id="default": root
    )
    knowledge.workspace.ensure_workspace_scaffold()
    monkeypatch.setattr(
        knowledge.normalizer, "normalize_to_markdown", lambda text: f"LLM_CLEANED\n{text}"
    )
    return root


@pytest.fixture
def client(workspace: Path):
    from config import get_settings
    from knowledge import commit_jobs

    commit_jobs._JOBS.clear()
    yield TestClient(app, headers={"X-Internal-Token": get_settings().gateway_internal_token})
    commit_jobs._JOBS.clear()


def _raw(workspace: Path, relative: str, content: str | bytes) -> Path:
    path = workspace / "raw" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return path


def _snapshot_tree(root: Path) -> dict[str, bytes | None]:
    """Snapshot every file under knowledge/, .qa_nodes.json, and raw/ with exact bytes."""
    snap: dict[str, bytes | None] = {}
    for folder in ("knowledge", "raw"):
        base = root / folder
        if base.exists():
            for p in sorted(base.rglob("*")):
                if p.is_file():
                    snap[p.relative_to(root).as_posix()] = p.read_bytes()
    nodes_path = root / "knowledge" / ".qa_nodes.json"
    snap["knowledge/.qa_nodes.json"] = nodes_path.read_bytes() if nodes_path.exists() else None
    return snap


# --- 1. 預覽（新表、重傳 same/new/conflict、格式錯誤、缺圖片、一般文件）與零副作用 ---


def test_preview_new_qa_table_and_ordinary_document_leaves_workspace_untouched(
    client: TestClient, workspace: Path,
):
    qa_nodes.create_node("zh", "中文")
    _raw(
        workspace,
        "faq.csv",
        "語言,第一層,第二層,問題,答案\n中文,服務,營業時間,幾點開門？,早上九點。\n",
    )
    _raw(workspace, "guide.md", "# 說明文件\n\n一般內容。\n")
    before = _snapshot_tree(workspace)

    response = client.post(
        "/brain/knowledge/raw/preview",
        json={"project_id": "default", "paths": ["faq.csv", "guide.md"]},
    )

    assert response.status_code == 200
    assert _snapshot_tree(workspace) == before
    files = response.json()["files"]
    assert files["guide.md"] == {"kind": "document"}
    assert files["faq.csv"] == {
        "kind": "qa",
        "target": "knowledge/qa/faq.csv",
        "existing": False,
        "errors": [],
        "duplicate_rows": 0,
        "questions": [
            {
                "question": "幾點開門？",
                "status": "new",
                "placement": ["中文", "服務", "營業時間"],
                "language": "zh",
            },
        ],
        "missing_images": [],
        "notes": [],
    }


def test_preview_does_not_initialize_an_unscaffolded_workspace(monkeypatch, tmp_path: Path):
    root = tmp_path / "unscaffolded"
    monkeypatch.setattr(knowledge.workspace, "get_workspace_root", lambda project_id="default": root)
    _raw(root, "faq.csv", "問題,答案\nQ1,A1\n")
    before = sorted(path.relative_to(root) for path in root.rglob("*"))

    preview = preview_raw_documents("default", paths=["faq.csv"])["files"]["faq.csv"]

    assert preview["errors"] == []
    assert sorted(path.relative_to(root) for path in root.rglob("*")) == before


def test_preview_reupload_reports_same_new_and_conflict_without_touching_files(
    client: TestClient, workspace: Path,
):
    _raw(
        workspace,
        "faq.csv",
        "問題,答案,圖片,連結\n營業時間,早上九點,old.png,https://old.example\n停車資訊,後方有停車場,,\n",
    )
    commit_raw_documents("default")

    _raw(
        workspace,
        "faq.csv",
        "問題,答案,圖片,連結\n"
        "營業時間,改為早上十點,new.png,https://new.example\n"
        "停車資訊,後方有停車場,,\n"
        "門票費用,免費入場,,\n",
    )
    before = _snapshot_tree(workspace)

    response = client.post(
        "/brain/knowledge/raw/preview",
        json={"project_id": "default", "paths": ["faq.csv"]},
    )

    assert response.status_code == 200
    assert _snapshot_tree(workspace) == before
    preview = response.json()["files"]["faq.csv"]
    assert preview["kind"] == "qa"
    assert preview["target"] == "knowledge/qa/faq.md"
    assert preview["existing"] is True
    assert preview["errors"] == []
    assert preview["questions"] == [
        {
            "question": "營業時間",
            "status": "conflict",
            "placement": ["faq"],
            "language": "zh",
            "old": {
                "answer": "早上九點",
                "image": "old.png",
                "url": "https://old.example",
            },
            "new": {
                "answer": "改為早上十點",
                "image": "new.png",
                "url": "https://new.example",
            },
        },
        {
            "question": "停車資訊",
            "status": "same",
            "placement": ["faq"],
            "language": "zh",
        },
        {
            "question": "門票費用",
            "status": "new",
            "placement": ["faq"],
            "language": "zh",
        },
    ]


def test_preview_format_error_table_leaves_workspace_untouched(
    client: TestClient, workspace: Path,
):
    _raw(
        workspace,
        "bad.csv",
        "問題,答案,分類,第一層\nQ1,A1,中文/服務,服務\n,只有答案沒有題目,,\n",
    )
    before = _snapshot_tree(workspace)

    response = client.post(
        "/brain/knowledge/raw/preview",
        json={"project_id": "default", "paths": ["bad.csv"]},
    )

    assert response.status_code == 200
    assert _snapshot_tree(workspace) == before
    preview = response.json()["files"]["bad.csv"]
    assert preview["kind"] == "qa"
    assert len(preview["errors"]) == 2
    assert "同時填了「分類」和「第一層／第二層」" in preview["errors"][0]
    assert "只有答案、沒有題目" in preview["errors"][1]
    commit = commit_raw_documents("default", paths=["bad.csv"])
    assert commit["skip_reasons"]["bad.csv"] == "\n".join(preview["errors"])


def test_preview_missing_images_table_lists_questions_and_leaves_workspace_untouched(
    client: TestClient, workspace: Path,
):
    images_dir = workspace / "knowledge" / ".qa_images"
    images_dir.mkdir(parents=True, exist_ok=True)
    (images_dir / "exists.png").write_bytes(b"png")

    _raw(
        workspace,
        "imgs.csv",
        "問題,答案,圖片\nQ1,A1,missing_a.png\nQ2,A2,exists.png\nQ3,A3,missing_a.png\nQ4,A4,missing_b.jpg\n",
    )
    before = _snapshot_tree(workspace)

    response = client.post(
        "/brain/knowledge/raw/preview",
        json={"project_id": "default", "paths": ["imgs.csv"]},
    )

    assert response.status_code == 200
    assert _snapshot_tree(workspace) == before
    preview = response.json()["files"]["imgs.csv"]
    assert preview["missing_images"] == [
        {"image": "missing_a.png", "questions": ["Q1", "Q3"]},
        {"image": "missing_b.jpg", "questions": ["Q4"]},
    ]
    assert any("圖片找不到" in note for note in preview["notes"])


# --- 2. 預覽的錯誤文字和實際匯入擋下時的文字一模一樣 ---


@pytest.mark.parametrize(
    "csv_content",
    [
        "問題,答案,分類,第一層\nQ1,A1,中文/服務,服務\n",
        "問題,答案,第二層\nQ1,A1,營業時間\n",
        "問題,答案,分類\nQ1,A1,中文/甲/乙/丙\n",
        "問題,答案\n,只有答案的一列\n",
        "問題,答案\nQ1,答案一\nQ1,答案二\n",
        '問題,答案\nQ1,"第一段\n## 這行會拆壞"\n',
        "問題,答案\n",
    ],
)
def test_preview_error_text_matches_commit_refusal_string_exactly(
    workspace: Path, csv_content: str,
):
    _raw(workspace, "broken.csv", csv_content)

    preview = preview_raw_documents("default", paths=["broken.csv"])["files"]["broken.csv"]
    commit_result = commit_raw_documents("default", paths=["broken.csv"])

    assert commit_result["skipped"] == ["broken.csv"]
    assert preview["errors"] == [commit_result["skip_reasons"]["broken.csv"]]


@pytest.mark.parametrize("existing", [False, True], ids=["new", "reupload"])
def test_duplicate_rows_with_different_images_refuse_preview_and_commit(workspace: Path, existing: bool):
    if existing:
        _raw(workspace, "faq.csv", "問題,答案\nQ1,A1\n")
        assert commit_raw_documents("default")["committed"]
    _raw(workspace, "faq.csv", "問題,答案,圖片\nQ1,A1,a.png\nQ1,A1,b.png\nQ2,A2,\n")
    before = _snapshot_tree(workspace)

    preview = preview_raw_documents("default", paths=["faq.csv"])["files"]["faq.csv"]
    commit = commit_raw_documents("default", paths=["faq.csv"], decisions={"faq.csv": {"conflicts": {}}})

    assert preview["errors"] == [commit["skip_reasons"]["faq.csv"]]
    assert commit["skipped"] == ["faq.csv"]
    assert _snapshot_tree(workspace) == before


def test_preview_counts_all_repeated_rows_and_lists_each_question_once(workspace: Path):
    _raw(workspace, "faq.csv", "問題,答案\nQ1,A1\nQ1,A1\nQ1,A1\nQ2,A2\nQ3,A3\nQ3,A3\n")
    preview = preview_raw_documents("default", paths=["faq.csv"])["files"]["faq.csv"]

    assert preview["errors"] == []
    assert preview["duplicate_rows"] == 5
    assert [item["question"] for item in preview["questions"]] == ["Q1", "Q2", "Q3"]


@pytest.mark.parametrize("detached", [False, True], ids=["deleted-category", "detached-question"])
def test_preview_placement_matches_commit_for_removed_menu_entries(workspace: Path, detached: bool):
    qa_nodes.create_node("zh", "中文")
    _raw(workspace, "faq.csv", "問題,答案\nQ1,A1\nQ2,A2\n")
    initial = commit_raw_documents("default")["results"]["faq.csv"]
    target, node_id = initial["target"], initial["qa_node_id"]
    if detached:
        qa_nodes.remove_qa_entry_from_node(node_id, "Q1", source_path=target)
    else:
        qa_nodes.delete_node(node_id, "default")
    _raw(
        workspace, "faq.csv",
        "問題,答案,分類\nQ1,A1,中文/新分類\nQ2,A2,中文/新分類\nQ3,A3,中文/新分類\n",
    )
    preview = preview_raw_documents("default", paths=["faq.csv"])["files"]["faq.csv"]
    predicted = {item["question"]: item["placement"] for item in preview["questions"]}

    assert commit_raw_documents("default", paths=["faq.csv"])["committed"] == [target]
    actual = dict.fromkeys(predicted)
    for language in qa_nodes.get_node_tree():
        for category in language["children"]:
            for entry in category["qa_entries"]:
                actual[entry["question"]] = [language["label"], category["label"]]
    assert actual == predicted
    assert actual == (
        {"Q1": None, "Q2": ["中文", "faq"], "Q3": ["中文", "新分類"]}
        if detached else {"Q1": None, "Q2": None, "Q3": None}
    )


def test_overwrite_preserves_empty_image_and_url_but_uses_supplied_values(workspace: Path):
    from knowledge.qa_csv import parse_qa_markdown

    _raw(
        workspace, "faq.csv",
        "問題,答案,圖片,連結\nQ1,A1,old.png,https://old.example\nQ2,A2,old.png,https://old.example\n",
    )
    initial = commit_raw_documents("default")["results"]["faq.csv"]
    _raw(
        workspace, "faq.csv",
        "問題,答案,圖片,連結\nQ1,新答案,,\nQ2,新答案,new.png,https://new.example\n",
    )
    result = commit_raw_documents(
        "default", paths=["faq.csv"],
        decisions={"faq.csv": {"conflicts": {"Q1": "overwrite", "Q2": "overwrite"}}},
    )

    assert result["committed"] == [initial["target"]]
    entries = parse_qa_markdown((workspace / initial["target"]).read_text())
    assert [(entry["a"], entry["img"], entry["url"]) for entry in entries] == [
        ("新答案", "old.png", "https://old.example"),
        ("新答案", "new.png", "https://new.example"),
    ]


# --- 3. 匯入決定（overwrite、keep、both、later）與（新2）遞增 ---


def test_commit_decisions_overwrite_keep_both_and_later(workspace: Path):
    _raw(
        workspace,
        "faq.csv",
        "問題,答案,display\n"
        "Q_overwrite,舊答案1,false\n"
        "Q_keep,舊答案2,\n"
        "Q_both,舊答案3,\n"
        "Q_later,舊答案4,\n",
    )
    first = commit_raw_documents("default")
    node_id = first["results"]["faq.csv"]["qa_node_id"]

    _raw(
        workspace,
        "faq.csv",
        "問題,答案,圖片,連結\n"
        "Q_overwrite,新答案1,new1.png,https://one.example\n"
        "Q_keep,新答案2,,\n"
        "Q_both,新答案3,both.png,\n"
        "Q_later,待調整的新答案4,,\n",
    )
    second = commit_raw_documents(
        "default",
        paths=["faq.csv"],
        decisions={
            "faq.csv": {
                "conflicts": {
                    "Q_overwrite": "overwrite",
                    "Q_keep": "keep",
                    "Q_both": "both",
                    "Q_later": "later",
                },
            },
        },
    )

    assert second["committed"] == ["knowledge/qa/faq.md"]
    file_result = second["results"]["faq.csv"]
    assert file_result["both"] == ["Q_both（新）"]
    assert file_result["later"] == [{"question": "Q_later", "answer": "待調整的新答案4"}]
    assert file_result["origin_path"].startswith("archive/originals/faq")
    assert (workspace / file_result["origin_path"]).is_file()

    from knowledge.qa_csv import parse_qa_markdown

    doc_text = (workspace / "knowledge" / "qa" / "faq.md").read_text(encoding="utf-8")
    by_q = {item["q"]: item for item in parse_qa_markdown(doc_text)}
    # overwrite: 更新答案、圖片、連結，保留原本的隱藏狀態
    assert by_q["Q_overwrite"]["a"] == "新答案1"
    assert by_q["Q_overwrite"]["img"] == "new1.png"
    assert by_q["Q_overwrite"]["url"] == "https://one.example"
    assert by_q["Q_overwrite"]["hidden"] is True
    # keep: 維持舊答案
    assert by_q["Q_keep"]["a"] == "舊答案2"
    # both: 舊題不動，新題以「（新）」加入並設為隱藏
    assert by_q["Q_both"]["a"] == "舊答案3"
    assert by_q["Q_both"]["hidden"] is False
    assert by_q["Q_both（新）"]["a"] == "新答案3"
    assert by_q["Q_both（新）"]["img"] == "both.png"
    assert by_q["Q_both（新）"]["hidden"] is True
    # later: 檔案裡維持舊答案
    assert by_q["Q_later"]["a"] == "舊答案4"

    node = qa_nodes.get_node(node_id, "default")
    assert node is not None
    entries = {e["question"]: e for e in node["qa_entries"]}
    assert entries["Q_overwrite"]["hidden"] is True
    assert entries["Q_overwrite"]["image_id"] == "new1.png"
    assert entries["Q_both（新）"]["hidden"] is True
    assert entries["Q_both（新）"]["image_id"] == "both.png"


def test_commit_decision_both_increments_suffix_when_new_name_already_exists(workspace: Path):
    _raw(workspace, "faq.csv", "問題,答案\nQ1,第一版\n")
    commit_raw_documents("default")

    _raw(workspace, "faq.csv", "問題,答案\nQ1,第二版\n")
    second = commit_raw_documents(
        "default",
        decisions={"faq.csv": {"conflicts": {"Q1": "both"}}},
    )
    assert second["results"]["faq.csv"]["both"] == ["Q1（新）"]

    _raw(workspace, "faq.csv", "問題,答案\nQ1,第三版\n")
    third = commit_raw_documents(
        "default",
        decisions={"faq.csv": {"conflicts": {"Q1": "both"}}},
    )
    assert third["results"]["faq.csv"]["both"] == ["Q1（新2）"]

    from knowledge.qa_csv import parse_qa_markdown

    doc_text = (workspace / "knowledge" / "qa" / "faq.md").read_text(encoding="utf-8")
    by_q = {item["q"]: item for item in parse_qa_markdown(doc_text)}
    assert by_q["Q1"]["a"] == "第一版"
    assert by_q["Q1（新）"]["a"] == "第二版" and by_q["Q1（新）"]["hidden"] is True
    assert by_q["Q1（新2）"]["a"] == "第三版" and by_q["Q1（新2）"]["hidden"] is True


# --- 4. 沒帶 decisions 或部分衝突沒決定時，維持整份拒絕 ---


def test_reupload_conflict_without_complete_decisions_is_refused_whole(workspace: Path):
    _raw(workspace, "faq.csv", "問題,答案\nQ1,A1\nQ2,A2\n")
    commit_raw_documents("default")
    target = workspace / "knowledge" / "qa" / "faq.md"
    before = target.read_text(encoding="utf-8")

    # 只決定了 Q1，Q2 沒決定 -> 整份不匯入
    _raw(workspace, "faq.csv", "問題,答案\nQ1,新A1\nQ2,新A2\n")
    partial = commit_raw_documents(
        "default",
        decisions={"faq.csv": {"conflicts": {"Q1": "overwrite"}}},
    )
    assert partial["committed"] == []
    assert partial["skipped"] == ["faq.csv"]
    assert "「Q2」" in partial["skip_reasons"]["faq.csv"]
    assert target.read_text(encoding="utf-8") == before


# --- 5. images 替換：補傳的 id 寫進文件；不存在的 id 整份不匯入 ---


def test_commit_images_decision_replaces_image_id_and_refuses_nonexistent_id(workspace: Path):
    images_dir = workspace / "knowledge" / ".qa_images"
    images_dir.mkdir(parents=True, exist_ok=True)
    (images_dir / "uploaded_123.png").write_bytes(b"png")

    # 補傳的 image_id 不存在 -> 整份不匯入
    _raw(workspace, "faq.csv", "問題,答案,圖片\nQ1,A1,raw_pic.png\n")
    refused = commit_raw_documents(
        "default",
        decisions={"faq.csv": {"images": {"raw_pic.png": "no_such_image.png"}}},
    )
    assert refused["committed"] == []
    assert refused["skipped"] == ["faq.csv"]
    assert "no_such_image.png" in refused["skip_reasons"]["faq.csv"]
    assert not (workspace / "knowledge" / "qa" / "faq.md").exists()
    assert (workspace / "raw" / "faq.csv").exists()

    # 補傳的 image_id 存在 -> 替換寫入文件與節點，且不再提示圖片找不到
    accepted = commit_raw_documents(
        "default",
        decisions={"faq.csv": {"images": {"raw_pic.png": "uploaded_123.png"}}},
    )
    assert accepted["committed"] == ["knowledge/qa/faq.md"]
    assert "notes" not in accepted["results"]["faq.csv"]

    from knowledge.qa_csv import parse_qa_markdown

    doc_text = (workspace / "knowledge" / "qa" / "faq.md").read_text(encoding="utf-8")
    items = parse_qa_markdown(doc_text)
    assert items[0]["img"] == "uploaded_123.png"
    node_id = accepted["results"]["faq.csv"]["qa_node_id"]
    node = qa_nodes.get_node(node_id, "default")
    assert node is not None
    assert node["qa_entries"][0]["image_id"] == "uploaded_123.png"


@pytest.mark.asyncio
async def test_commit_route_forwards_decisions_to_job_results(workspace: Path, monkeypatch):
    import routes.knowledge
    from fastapi import Response
    from knowledge import commit_jobs
    from protocol.schemas import KnowledgeFileDecision, KnowledgeRawCommitRequest

    commit_jobs._JOBS.clear()
    monkeypatch.setattr(routes.knowledge, "schedule_reindex", lambda project_id: None)

    _raw(workspace, "faq.csv", "問題,答案\nQ1,舊A1\nQ2,舊A2\n")
    commit_raw_documents("default")

    _raw(workspace, "faq.csv", "問題,答案\nQ1,新A1\nQ2,新A2\n")
    payload = KnowledgeRawCommitRequest(
        project_id="default",
        paths=["faq.csv"],
        normalize=False,
        decisions={
            "faq.csv": KnowledgeFileDecision(
                conflicts={"Q1": "both", "Q2": "later"},
            ),
        },
    )
    response = Response()
    await routes.knowledge.commit_knowledge_raw_route(payload, response)
    assert response.status_code == 202

    for _ in range(100):
        snapshot = await routes.knowledge.commit_status_route(project_id="default")
        if snapshot["state"] != "running":
            break
        await asyncio.sleep(0.05)

    assert snapshot["state"] == "done"
    res = snapshot["results"]["faq.csv"]
    assert res["both"] == ["Q1（新）"]
    assert res["later"] == [{"question": "Q2", "answer": "新A2"}]
    assert res["origin_path"].startswith("archive/originals/faq")

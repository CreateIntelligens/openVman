"""Seed the ESG project's Quick Reply prompts without deleting other QA data."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from knowledge.doc_meta import upsert_document_meta
from knowledge.knowledge_admin import save_workspace_document
from knowledge.qa_nodes import create_node, get_node, update_node


DEFAULT_PROJECT_ID = "esg-7dea843a0d"
NODE_ID = "esg-set-future-quick-replies"
NODE_LABEL = "三立 ESG"
SOURCE_PATH = "knowledge/qa/esg_set_future_quick_replies.md"

# Keep these in the same order as the ESG kiosk's source quick-question list.
QUICK_REPLIES = (
    "永續經營",
    "環境保護｜綠色營運",
    "社會責任｜幸福職場",
    "公司治理｜創新轉型",
    "三立永續行動－低碳節能",
    "三立永續行動－資源管理",
    "三立永續行動－健康福祉",
    "三立永續行動－綠色製播",
    "三立永續行動－生物多樣性",
    "三立永續行動－永續城鄉",
    "三立永續行動－專業經營",
    "三立永續行動－SDGs 倡議",
)


def _render_source(questions: Sequence[str]) -> str:
    return "\n".join(f"## {question}\n" for question in questions)


def _entries(questions: Sequence[str]) -> list[dict[str, object]]:
    return [
        {
            "question": question,
            "source_path": SOURCE_PATH,
            "hidden": False,
            "image_id": None,
        }
        for question in questions
    ]


def seed_esg_quick_replies(project_id: str = DEFAULT_PROJECT_ID) -> dict[str, object]:
    """Upsert the managed ESG prompts and preserve unrelated node entries."""
    save_workspace_document(
        SOURCE_PATH,
        _render_source(QUICK_REPLIES),
        project_id,
    )
    upsert_document_meta(SOURCE_PATH, project_id, source_type="qa")

    managed_entries = _entries(QUICK_REPLIES)
    node = get_node(NODE_ID, project_id=project_id)
    if node is None:
        create_node(
            node_id=NODE_ID,
            label=NODE_LABEL,
            order=0.0,
            qa_entries=managed_entries,
            project_id=project_id,
        )
        created = True
    else:
        unrelated_entries = [
            entry
            for entry in node.get("qa_entries", [])
            if entry.get("source_path") != SOURCE_PATH
        ]
        update_node(
            NODE_ID,
            {
                "label": NODE_LABEL,
                "hidden": False,
                "qa_entries": unrelated_entries + managed_entries,
            },
            project_id=project_id,
        )
        created = False

    return {
        "created": created,
        "node_id": NODE_ID,
        "project_id": project_id,
        "quick_reply_count": len(QUICK_REPLIES),
        "source_path": SOURCE_PATH,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Idempotently seed the ESG Quick Reply prompts.",
    )
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    args = parser.parse_args()
    print(
        json.dumps(
            seed_esg_quick_replies(args.project_id),
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

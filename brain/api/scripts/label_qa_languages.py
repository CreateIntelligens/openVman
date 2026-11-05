"""Label each row of a project's QA CSVs with its language, once.

標過的列不會被改，人工修正不會被下一次蓋掉。結果寫進 CSV 的 language 欄，可以直接看、直接改。
預設只顯示統計，加 --write 才寫入；寫入後會由下次重建索引帶進檢索。

    docker exec -w /app openvman-api-1 python -m scripts.label_qa_languages <project_id>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure the api package root is importable when invoked via ``python3 -m``.
_API_ROOT = Path(__file__).resolve().parents[1]
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

from knowledge.doc_meta import load_doc_meta  # noqa: E402
from knowledge.knowledge_admin import (  # noqa: E402
    resolve_workspace_document,
    save_workspace_document,
)
from knowledge.qa_csv import label_qa_csv_languages  # noqa: E402
from memory.language_detect import detect_document_language, detect_row_language  # noqa: E402


def label_project(project_id: str, write: bool = False) -> dict[str, dict[str, int]]:
    """Return per-file language counts, saving the labels when ``write`` is set."""
    results: dict[str, dict[str, int]] = {}
    for path, meta in sorted(load_doc_meta(project_id).items()):
        if meta.get("source_type") != "qa" or not path.lower().endswith(".csv"):
            continue
        # 人工指定語言的文件（例如台語）不打標：規則判不出來，標了反而把排序改壞。
        if meta.get("language_source") == "manual":
            continue
        doc_path = resolve_workspace_document(path, project_id)
        if not doc_path.exists():
            continue
        # 太短判斷不出來的列跟著文件語言，不要全部變成專案的主要語言。預覽不能順手寫 meta，
        # 所以不用會存檔的 resolve_document_languages。
        fallback = meta.get("language") or detect_document_language(
            doc_path.read_text(encoding="utf-8-sig", errors="replace")[:4000]
        )
        try:
            content, counts = label_qa_csv_languages(
                doc_path.read_bytes(),
                lambda text, default=fallback: detect_row_language(text, default),
            )
        except ValueError as exc:
            print(f"略過 {path}：{exc}", file=sys.stderr)
            continue
        results[path] = counts
        if write:
            save_workspace_document(path, content, project_id)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_id")
    parser.add_argument("--write", action="store_true", help="實際寫入 language 欄")
    args = parser.parse_args()
    for path, counts in label_project(args.project_id, write=args.write).items():
        print(path, counts)


if __name__ == "__main__":
    main()

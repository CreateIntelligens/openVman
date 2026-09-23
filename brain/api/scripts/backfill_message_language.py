"""Fill messages.language for user messages written before the column existed.

欄位是 NULL 的舊訊息在列表時只能靠規則補算，長段中英混雜（例如 A2A 測試句）
與亂碼（"su3cl"）會判錯。這支一次性腳本逐則問 Jev，Jev 失敗就寫規則結果。

    docker exec -w /app openvman-api-1 python -m scripts.backfill_message_language --dry-run
    docker exec -w /app openvman-api-1 python -m scripts.backfill_message_language
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

# Ensure the api package root is importable when invoked via ``python3 -m``.
_API_ROOT = Path(__file__).resolve().parents[1]
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

from core.jev_client import jev_available
from infra.project_context import get_data_root
from memory.language_detect import detect_language, detect_language_with_jev
from memory.memory import get_session_store


def _resolve(text: str, use_jev: bool) -> tuple[str, str]:
    if use_jev:
        try:
            return detect_language_with_jev(text), "jev"
        except Exception as exc:  # noqa: BLE001 - 單則失敗就退回規則
            print(f"  jev failed ({type(exc).__name__}), using rule", file=sys.stderr)
    return detect_language(text), "rule"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="只列出結果，不寫入")
    args = parser.parse_args()

    use_jev = jev_available()
    print(f"resolver: {'jev' if use_jev else 'rule only (no TYPESAFE_API_KEY)'}")
    totals: Counter[str] = Counter()
    for project_dir in sorted(get_data_root().iterdir()):
        if not (project_dir / "sessions.db").exists():
            continue
        store = get_session_store(project_dir.name)
        rows = store.list_user_messages_without_language()
        for message_id, content in rows:
            language, source = _resolve(content, use_jev)
            totals[language] += 1
            rule = detect_language(content)
            if language != rule:
                print(f"  {project_dir.name} #{message_id} {rule}->{language} ({source}): {content[:50]!r}")
            if not args.dry_run:
                store.update_message_language(message_id, language)
        if rows:
            print(f"{project_dir.name}: {len(rows)} messages")
    print(f"{'would set' if args.dry_run else 'set'}: {dict(totals)}")


if __name__ == "__main__":
    main()

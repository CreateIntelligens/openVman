"""Classify existing QA images so the first reply using one does not wait.

新上傳的圖在上傳時就判斷；這支補既有的圖，可重複執行，判斷過的不會重算。

    docker exec -w /app openvman-api-1 python -m scripts.classify_qa_images
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

# Ensure the api package root is importable when invoked via ``python3 -m``.
_API_ROOT = Path(__file__).resolve().parents[1]
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

from infra.project_context import get_data_root  # noqa: E402
from knowledge.qa_images import ALLOWED_QA_IMAGE_SUFFIXES, qa_image_kind  # noqa: E402


def main() -> None:
    for project_dir in sorted(path for path in get_data_root().iterdir() if path.is_dir()):
        images_dir = project_dir / "workspace" / "knowledge" / ".qa_images"
        if not images_dir.is_dir():
            continue
        kinds = Counter(
            qa_image_kind(image.name, project_dir.name)
            for image in sorted(images_dir.iterdir())
            if image.suffix.lower() in ALLOWED_QA_IMAGE_SUFFIXES
        )
        print(project_dir.name, dict(kinds))


if __name__ == "__main__":
    main()

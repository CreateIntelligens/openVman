"""Content fingerprints that decide whether a document needs re-indexing.

切塊、索引、圖譜三邊都要問「這份文件變了沒」，所以指紋不屬於其中任何一個
模組。放在這裡，大家平行地依賴它，不必互相反向 import。

指紋裡含索引格式版本：索引欄位或切塊規格改變時升版，讓內容未變的既有文件
也會重建一次。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

KNOWLEDGE_INDEX_FORMAT_VERSION = "2"


def fingerprint_document(path: Path) -> str:
    """Return the SHA-256 fingerprint of a document's content and index format."""
    digest = hashlib.sha256()
    digest.update(f"openvman-knowledge-v{KNOWLEDGE_INDEX_FORMAT_VERSION}\0".encode())
    digest.update(path.read_bytes())
    return digest.hexdigest()

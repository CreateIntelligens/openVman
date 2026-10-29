"""Document upload checks: extension whitelist, PDF magic and zip-bomb guard.

docx / pptx / xlsx 都是 zip；解壓後的總量和檔案數要先擋，轉檔器才不會被炸。
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import IO, Any

from app.utils.upload import UnsupportedUploadError, UploadTooLargeError, format_limit

OFFICE_ZIP_SUFFIXES = frozenset({".docx", ".pptx", ".xlsx"})
PLAINTEXT_DOCUMENT_SUFFIXES = frozenset({".md", ".markdown", ".txt", ".csv"})
# 知識庫上傳、raw 暫存區與 documents/convert 共用同一份清單；Brain 的 raw 區也照這份。
DOCUMENT_SUFFIXES = PLAINTEXT_DOCUMENT_SUFFIXES | OFFICE_ZIP_SUFFIXES | frozenset(
    {".pdf", ".html", ".htm"},
)


def require_document_suffix(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in DOCUMENT_SUFFIXES:
        allowed = "、".join(sorted(DOCUMENT_SUFFIXES))
        raise UnsupportedUploadError(f"不支援的文件格式，僅接受 {allowed}")
    return suffix


def check_zip_archive(source: str | IO[bytes], *, max_uncompressed_bytes: int, max_entries: int) -> None:
    """Reject archives whose declared contents are too many or too large.

    Python's zipfile (used by python-docx / openpyxl / Docling) stops reading an
    entry at its declared size, so bounding the declared sizes bounds the work.
    """
    try:
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
    except (zipfile.BadZipFile, OSError) as exc:
        raise UnsupportedUploadError("Office 文件內容不是有效的壓縮格式") from exc
    if len(entries) > max_entries:
        raise UploadTooLargeError(0, f"文件內含檔案數超過上限（{max_entries} 個）")
    total = sum(entry.file_size for entry in entries)
    if total > max_uncompressed_bytes:
        raise UploadTooLargeError(
            max_uncompressed_bytes,
            f"文件解壓後超過大小上限（{format_limit(max_uncompressed_bytes)}）",
        )


def check_document_upload(source: str | IO[bytes], suffix: str, *, cfg: Any) -> None:
    """Run the content checks that apply to a stored document upload."""
    suffix = suffix.lower()
    if suffix in OFFICE_ZIP_SUFFIXES:
        check_zip_archive(
            source,
            max_uncompressed_bytes=cfg.document_zip_max_uncompressed_bytes,
            max_entries=cfg.document_zip_max_entries,
        )
    elif suffix == ".pdf":
        if isinstance(source, str):
            with Path(source).open("rb") as handle:
                head = handle.read(1024)
        else:
            head = source.read(1024)
            source.seek(0)
        if b"%PDF-" not in head:
            raise UnsupportedUploadError("PDF 內容不是有效的 PDF")

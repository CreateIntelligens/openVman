"""Validate path fragments supplied by knowledge upload and import clients."""

from pathlib import Path


def sanitize_relative_subpath(raw: str) -> Path:
    """Normalize a client-supplied relative path, rejecting traversal.

    Strips leading slashes and rejects any segment that is empty, ``.`` or
    ``..`` so callers cannot escape the intended ``target_dir``.
    """
    cleaned = raw.strip().lstrip("/\\")
    if not cleaned:
        raise ValueError("relative_path 不可為空")
    parts = Path(cleaned).parts
    for part in parts:
        if part in ("", ".", "..") or part.startswith(("/", "\\")):
            raise ValueError("relative_path 不允許 .. 或絕對路徑片段")
    return Path(*parts)


def raw_relative_path(path: str, raw_root: Path) -> str:
    parts = path.split("/")
    # 反斜線在這裡只是檔名的一部分，但沒有這個檔案時多半是 Windows 路徑，一樣拒絕。
    # 真的有這個檔名時要放行，否則它移不掉，「全部匯入」也會整批失敗。
    if any(part in ("", ".", "..") for part in parts) or (
        "\\" in path and not (raw_root / path).is_file()
    ):
        raise ValueError("檔案路徑不正確")
    # 上傳回應給 raw/a.csv，等待清單給 a.csv，兩種都收；raw/ 底下真的有 raw 資料夾時以實際檔案為準。
    relative = path
    if parts[0] == "raw" and len(parts) > 1 and not (raw_root / path).is_file():
        relative = "/".join(parts[1:])
    if not (raw_root / relative).resolve().is_relative_to(raw_root.resolve()):
        raise ValueError("檔案路徑不正確")
    return relative

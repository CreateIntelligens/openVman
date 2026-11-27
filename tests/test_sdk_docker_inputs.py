"""The avatar SDK build stage must copy every shared file the SDK imports.

The SDK is built inside frontend/admin/Dockerfile with only selected parts of
frontend/shared copied in; a new shared import that is not copied passes local
tests and only fails when CI builds the admin image.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK_SRC = ROOT / "frontend" / "avatar-sdk" / "src"
DOCKERFILE = ROOT / "frontend" / "admin" / "Dockerfile"
SHARED_IMPORT = re.compile(r"""from\s+["'](?:\.\./)+shared/([^"']+)["']""")


def _sdk_stage_copies() -> list[str]:
    copies = []
    in_sdk_stage = False
    for line in DOCKERFILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("FROM "):
            if in_sdk_stage:
                break
            continue
        if "COPY frontend/avatar-sdk/src" in line:
            in_sdk_stage = True
        match = re.match(r"COPY frontend/shared/(\S+)\s+/shared/(\S+)", line)
        if in_sdk_stage and match:
            copies.append(match.group(1))
    return copies


def _covered(target: str, copies: list[str]) -> bool:
    candidates = [target, f"{target}.ts", f"{target}.js", f"{target}/index.ts"]
    return any(
        candidate == copy or candidate.startswith(copy.rstrip("/") + "/")
        for candidate in candidates
        for copy in copies
    )


def test_sdk_stage_copies_every_shared_import():
    copies = _sdk_stage_copies()
    assert copies, "SDK build stage not found in frontend/admin/Dockerfile"
    missing = sorted({
        f"{path.relative_to(ROOT)} -> shared/{target}"
        for path in SDK_SRC.rglob("*.ts")
        for target in SHARED_IMPORT.findall(path.read_text(encoding="utf-8"))
        if not _covered(target, copies)
    })
    assert not missing, "add a COPY to the SDK stage of frontend/admin/Dockerfile: " + ", ".join(missing)

"""Nested bind mounts under a read-only parent need the directory to exist.

Docker 無法在唯讀掛載裡建立掛載點。compose 把 ./backend/app/assets/tts_references
掛到 /indextts-assets/tts_references，而父層 /indextts-assets 是 :ro，所以來源那
側的目錄必須先存在於磁碟上。

這個目錄空了就不會進 git，被清理掉之後 backend 起不來，而 runc 的錯誤訊息只說
"read-only file system"，看起來像 Docker 壞掉——實際上只是少了一個空目錄。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.requires_repo_root

ROOT = Path(__file__).resolve().parents[3]


def _bind_mounts(compose: str) -> list[tuple[str, str, bool]]:
    """Return (host_path, container_path, read_only) for每一條 bind mount。"""
    mounts = []
    for line in compose.splitlines():
        stripped = line.strip()
        match = re.fullmatch(r"-\s+(\./[^:]+):([^:]+)(:ro)?", stripped)
        if match:
            mounts.append((match.group(1), match.group(2), bool(match.group(3))))
    return mounts


def test_nested_mounts_under_a_readonly_parent_have_their_directory_on_disk():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    mounts = _bind_mounts(compose)
    readonly_parents = {
        container: host for host, container, ro in mounts if ro
    }

    missing = []
    for host, container, _ in mounts:
        for parent_container, parent_host in readonly_parents.items():
            if container == parent_container:
                continue
            if not container.startswith(f"{parent_container.rstrip('/')}/"):
                continue
            # 掛載點要在唯讀父層的「來源」那側先存在，Docker 才不用自己建。
            relative = container[len(parent_container.rstrip("/")) + 1:]
            required = ROOT / parent_host.lstrip("./") / relative
            if not required.is_dir():
                missing.append(f"{required} (for {container})")

    assert not missing, (
        "唯讀父層底下的巢狀掛載點必須先存在，否則容器起不來：\n"
        + "\n".join(missing)
    )

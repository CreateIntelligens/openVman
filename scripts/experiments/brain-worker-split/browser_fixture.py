"""Install an explicitly selected dev test avatar from stdin into disposable data."""

from __future__ import annotations

import sys
import tarfile

from app.auth.models import ROOT_USERNAME, ResourceType, ResourceVisibility
from app.auth.runtime import get_auth_runtime
from app.avatar.store import AvatarStore
from bootstrap import PROJECT, seed_backend

CHARACTER = "synthetic-worker-avatar"
VOICE = "zh-TW-HsiaoChenNeural"


def seed():
    seed_backend()
    # Read exactly two named files; never extract paths from the supplied archive.
    with tarfile.open(fileobj=sys.stdin.buffer, mode="r|*") as archive:
        assets = {}
        for member in archive:
            if member.name in {"01.webm", "combined_data.json.gz"}:
                handle = archive.extractfile(member)
                if handle is not None:
                    assets[member.name] = handle.read()
    assert set(assets) == {"01.webm", "combined_data.json.gz"}
    store = AvatarStore("/data/avatar")
    if not store.exists(CHARACTER):
        store.create_character(
            char_id=CHARACTER, label="Synthetic worker test fixture",
            video_bytes=assets["01.webm"],
            data_bytes=assets["combined_data.json.gz"],
        )
    runtime = get_auth_runtime()
    account = runtime.users.get_by_username(ROOT_USERNAME)
    assert account is not None
    for kind, identifier, metadata in (
        (ResourceType.AVATAR_CHARACTER, CHARACTER, {"label": "Synthetic worker test fixture"}),
        (ResourceType.CUSTOM_VOICE, VOICE, {"provider": "edge-tts", "label": "Synthetic Edge voice"}),
    ):
        existing = runtime.resources.get(kind, identifier)
        if existing is None:
            runtime.resources.register(
                resource_type=kind, resource_id=identifier,
                visibility=ResourceVisibility.PROJECT, owner_user_id=None,
                owner_project_id=PROJECT, metadata=metadata,
            )
        else:
            assert existing.visibility is ResourceVisibility.PROJECT
            assert existing.owner_project_id == PROJECT
        runtime.project_resource_assignments.assign(
            project_id=PROJECT, resource_type=kind, resource_id=identifier,
            assigned_by=account.id,
        )
    runtime.project_policies.replace(
        project_id=PROJECT, allowed_tts_voices=[VOICE], default_tts_voice=VOICE,
        allowed_characters=[CHARACTER], default_character_id=CHARACTER,
        tts_engine_order=["edge-tts"], updated_by=account.id,
    )
    print({"browser_fixture": CHARACTER, "project": PROJECT})


if __name__ == "__main__":
    seed()

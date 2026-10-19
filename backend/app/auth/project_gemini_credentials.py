"""Resolve encrypted project Gemini keys without crossing project boundaries."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException

from ._repository_base import now_iso
from .database import AuthDatabase
from .model_provider_repository import ModelProviderCipher
from .runtime import AuthRuntime, get_auth_runtime


class ProjectCredentialUnavailable(HTTPException):
    """A project's credential cannot be safely determined or decrypted."""

    def __init__(self) -> None:
        super().__init__(
            status_code=503,
            detail="project_gemini_credential_unavailable",
        )


@dataclass(frozen=True, slots=True)
class GeminiCredential:
    api_key: str = field(repr=False)
    source: Literal["project", "shared"]
    credential_id: str
    configured: bool


class ProjectGeminiCredentialRepository:
    def __init__(
        self, database: AuthDatabase, *, encryption_secret: str,
    ) -> None:
        self.database = database
        self.cipher = ModelProviderCipher(encryption_secret)

    def get(self, project_id: str) -> sqlite3.Row | None:
        with self.database.transaction() as connection:
            return connection.execute(
                "SELECT * FROM project_gemini_credentials WHERE project_id = ?",
                (project_id,),
            ).fetchone()

    def put(
        self, project_id: str, *, label: str, api_key: str, actor_id: str,
    ) -> None:
        normalized_key = api_key.strip()
        normalized_label = label.strip()
        if not normalized_key or len(normalized_key) > 4096:
            raise ValueError("api_key must contain 1 to 4096 characters")
        if not normalized_label or len(normalized_label) > 128:
            raise ValueError("label must contain 1 to 128 characters")
        ciphertext = self.cipher.encrypt("gemini", normalized_key)
        now = now_iso()
        with self.database.transaction(write=True) as connection:
            connection.execute(
                """
                INSERT INTO project_gemini_credentials(
                    project_id, credential_id, label, ciphertext,
                    updated_by, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    label = excluded.label,
                    ciphertext = excluded.ciphertext,
                    updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at
                """,
                (
                    project_id, f"pgc_{uuid4().hex}", normalized_label,
                    ciphertext, actor_id, now,
                ),
            )
            self._audit(
                connection, project_id, actor_id,
                "project_gemini_credential_updated", now,
            )

    def delete(self, project_id: str, *, actor_id: str) -> None:
        with self.database.transaction(write=True) as connection:
            connection.execute(
                "DELETE FROM project_gemini_credentials WHERE project_id = ?",
                (project_id,),
            )
            self._audit(
                connection, project_id, actor_id,
                "project_gemini_credential_removed", now_iso(),
            )

    @staticmethod
    def _audit(
        connection: sqlite3.Connection,
        project_id: str,
        actor_id: str,
        action: str,
        now: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO auth_audit_events(
                id, action, actor_user_id, target_user_id,
                created_at, metadata_json
            ) VALUES (?, ?, ?, NULL, ?, ?)
            """,
            (
                f"aud_{uuid4().hex}", action, actor_id, now,
                json.dumps({"project_id": project_id}),
            ),
        )


def project_gemini_repository(
    runtime: AuthRuntime,
) -> ProjectGeminiCredentialRepository:
    return ProjectGeminiCredentialRepository(
        runtime.database,
        encryption_secret=runtime.config.model_provider_encryption_secret,
    )


def resolve_gemini_credential(
    project_id: str | None,
    runtime: AuthRuntime | None = None,
) -> GeminiCredential:
    runtime = runtime or get_auth_runtime()
    if project_id is not None:
        try:
            repository = project_gemini_repository(runtime)
            row = repository.get(project_id)
        except (sqlite3.Error, OSError) as exc:
            # 無法讀取設定時，不能把「不知道有沒有綁 key」當成「沒綁」。
            raise ProjectCredentialUnavailable() from exc
        if row is not None:
            try:
                value = repository.cipher.decrypt("gemini", row["ciphertext"])
            except (AttributeError, TypeError, ValueError) as exc:
                raise ProjectCredentialUnavailable() from exc
            if not value or not value.strip():
                raise ProjectCredentialUnavailable()
            return GeminiCredential(
                api_key=value,
                source="project",
                credential_id=row["credential_id"],
                configured=True,
            )
    value = runtime.model_providers.get_credential(
        "gemini", env_default=runtime.config.gemini_api_key,
    )
    return GeminiCredential(
        api_key=value,
        source="shared",
        credential_id="gemini",
        configured=bool(value),
    )


def project_gemini_metadata(
    runtime: AuthRuntime, project_id: str,
) -> dict[str, object]:
    repository = project_gemini_repository(runtime)
    try:
        row = repository.get(project_id)
    except (sqlite3.Error, OSError) as exc:
        raise ProjectCredentialUnavailable() from exc
    if row is not None:
        try:
            value = repository.cipher.decrypt("gemini", row["ciphertext"])
        except (AttributeError, TypeError, ValueError):
            value = None
        # 管理頁仍需顯示綁定，才能讓 ROOT 移除或重填無法解密的金鑰。
        # 推論只走 resolver，解密失敗依然回 503，不使用這份 metadata。
        credential = GeminiCredential(
            api_key=value or "",
            source="project",
            credential_id=row["credential_id"],
            configured=True,
        )
    else:
        credential = resolve_gemini_credential(None, runtime)
    # 短 key 不能讓遮罩把整個值回傳出去。
    masked = ""
    if credential.configured:
        masked = "••••"
        if len(credential.api_key) > 4:
            masked += credential.api_key[-4:]
    return {
        "project_id": project_id,
        "source": credential.source,
        "label": row["label"] if row is not None else "",
        "configured": credential.configured,
        "masked": masked,
        "credential_id": credential.credential_id,
        "updated_at": row["updated_at"] if row is not None else None,
    }

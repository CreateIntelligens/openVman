"""A2A credential persistence manager with encrypted token storage and circle key rotation."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import stat
from typing import Any

from cryptography.fernet import Fernet
from pydantic import BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger("backend.gateway.a2a_store")


def compute_key_fingerprint(key: str, fingerprint_key: str = "") -> str:
    """Compute a stable keyed fingerprint without persisting the circle key."""
    clean = key.strip()
    if not clean:
        return "none"
    secret = fingerprint_key.strip() or "openvman-a2a-fingerprint-v1"
    digest = hmac.new(secret.encode("utf-8"), clean.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"hmac-sha256:{digest}"


# Alias for backward compatibility
compute_key_hash = compute_key_fingerprint


def _get_fernet(encryption_key: str) -> Fernet:
    """Derive a valid Fernet key; never fall back to a predictable default."""
    clean = encryption_key.strip()
    if not clean:
        raise ValueError("A2A credential encryption key is required")
    digest = hashlib.sha256(clean.encode("utf-8")).digest()
    b64_key = base64.urlsafe_b64encode(digest)
    return Fernet(b64_key)


class A2ACredentials(BaseModel):
    """Decrypted in-memory representation of A2A credentials."""

    agent_id: str = Field(..., alias="agentId")
    agent_token: str = Field(..., repr=False, alias="agentToken")
    circle_id: str = Field("public", alias="circleId")
    hub_url: str = Field(..., alias="hubUrl")
    hub_key_fingerprint: str = Field(..., alias="hubKeyFingerprint")
    display_name: str = Field("openVman", alias="displayName")
    registered_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        alias="registeredAt",
    )
    expires_at: str = Field("", alias="expiresAt")

    model_config = ConfigDict(populate_by_name=True)

    @property
    def hub_key_hash(self) -> str:
        return self.hub_key_fingerprint

    @model_validator(mode="before")
    @classmethod
    def _remap_legacy_hash(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "hubKeyHash" in data and "hubKeyFingerprint" not in data:
                data["hubKeyFingerprint"] = data["hubKeyHash"]
            if "hub_key_hash" in data and "hub_key_fingerprint" not in data:
                data["hub_key_fingerprint"] = data["hub_key_hash"]
        return data


class A2ACredentialStore:
    """Manages file-based storage of A2A credentials with mode 0600 and at-rest encryption."""

    def __init__(self, filepath: str | Path, encryption_key: str = ""):
        self.filepath = Path(filepath)
        self.encryption_key = encryption_key

    def load(self, expected_hub_url: str, current_hub_key: str) -> A2ACredentials | None:
        """Load credentials from disk, verify Hub URL, fingerprint, and decrypt agent token."""
        if not self.filepath.exists():
            logger.debug("A2A credentials file does not exist: %s", self.filepath)
            return None

        try:
            content = self.filepath.read_text(encoding="utf-8")
            data = json.loads(content)
        except Exception as e:
            logger.warning("Corrupt A2A credentials file at %s: %s", self.filepath, e)
            return None
        if not isinstance(data, dict):
            logger.warning("A2A credentials file must contain a JSON object")
            return None

        if stat.S_IMODE(self.filepath.stat().st_mode) != 0o600:
            logger.warning("A2A credentials file has unsafe permissions")
            return None

        schema_version = data.get("schemaVersion", 1)
        if schema_version != 1:
            logger.warning("Unsupported A2A credential schema version: %s", schema_version)
            return None

        # Verify Hub URL
        saved_hub = data.get("hubUrl", "").rstrip("/")
        if saved_hub != expected_hub_url.rstrip("/"):
            logger.info("A2A Hub URL changed from %s to %s; invalidating credentials", saved_hub, expected_hub_url)
            return None

        # Verify Key Fingerprint (detects key rotation)
        expected_fp = compute_key_fingerprint(current_hub_key, self.encryption_key)
        saved_fp = data.get("hubKeyFingerprint") or data.get("hubKeyHash", "")

        if saved_fp != expected_fp:
            logger.info("A2A Hub Key rotated (fingerprint mismatch); invalidating credentials")
            return None

        # Decrypt agent token
        encrypted_token = data.get("encryptedAgentToken")
        agent_token = ""
        if encrypted_token:
            try:
                fernet = _get_fernet(self.encryption_key)
                decrypted = fernet.decrypt(encrypted_token.encode("utf-8")).decode("utf-8")
                agent_token = decrypted
            except Exception as exc:
                logger.warning("Failed to decrypt A2A agentToken: %s", exc)
                return None
        else:
            # Plaintext legacy tokens are deliberately rejected. Re-register
            # after configuring an encryption key instead of importing secrets.
            logger.warning("Plaintext A2A credentials are not accepted")
            return None

        if not agent_token:
            return None

        try:
            creds = A2ACredentials(
                agentId=data["agentId"],
                agentToken=agent_token,
                circleId=data.get("circleId", "public"),
                hubUrl=expected_hub_url,
                hubKeyFingerprint=expected_fp,
                displayName=data.get("displayName", "openVman"),
                registeredAt=data.get("registeredAt", ""),
                expiresAt=data.get("expiresAt", ""),
            )
            return creds
        except Exception as exc:
            logger.warning("Failed to construct A2ACredentials: %s", exc)
            return None

    def save(self, creds: A2ACredentials) -> None:
        """Encrypt token, atomically write credentials with mode 0600."""
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.filepath.with_suffix(f".tmp.{os.getpid()}")

        fernet = _get_fernet(self.encryption_key)
        encrypted_token = fernet.encrypt(creds.agent_token.encode("utf-8")).decode("utf-8")

        payload = {
            "schemaVersion": 1,
            "agentId": creds.agent_id,
            "encryptedAgentToken": encrypted_token,
            "circleId": creds.circle_id,
            "hubUrl": creds.hub_url,
            "hubKeyFingerprint": creds.hub_key_fingerprint,
            "displayName": creds.display_name,
            "registeredAt": creds.registered_at,
            "expiresAt": creds.expires_at,
        }
        content = json.dumps(payload, indent=2)

        try:
            # Create file with 0600 permissions
            fd = os.open(str(temp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            temp_path.replace(self.filepath)
            os.chmod(self.filepath, 0o600)
            logger.info("Saved encrypted A2A credentials to %s for agent %s", self.filepath, creds.agent_id)
        except Exception as exc:
            logger.error("Failed to write A2A credentials to %s: %s", self.filepath, exc)
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            raise

    def clear(self) -> None:
        """Remove cached credentials if present."""
        if self.filepath.exists():
            try:
                self.filepath.unlink()
                logger.info("Cleared A2A credentials at %s", self.filepath)
            except Exception as e:
                logger.warning("Failed to remove credentials %s: %s", self.filepath, e)

"""Encrypted temporary passwords for administrator-only batch management."""

from __future__ import annotations

import base64
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken


class TemporaryPasswordCipher:
    def __init__(self, secret: str) -> None:
        self._secret = secret.encode("utf-8")
        if len(self._secret) < 32:
            raise ValueError("temporary password secret must be at least 32 bytes")

    def _cipher(self, locator: str) -> Fernet:
        # Separate this key from session signing and bind each saved password
        # to its account locator so swapped database cells cannot decrypt.
        key = hmac.digest(
            self._secret,
            b"openvman:temporary-password:v1\0" + locator.encode("utf-8"),
            hashlib.sha256,
        )
        return Fernet(base64.urlsafe_b64encode(key))

    def encrypt(self, password: str, locator: str) -> str:
        return self._cipher(locator).encrypt(password.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str | None, locator: str) -> str | None:
        if not ciphertext:
            return None
        try:
            return self._cipher(locator).decrypt(
                ciphertext.encode("utf-8"),
            ).decode("utf-8")
        except (InvalidToken, UnicodeError):
            # Legacy rows and unavailable encryption keys must not prevent
            # listing a batch or authenticating against its existing hash.
            return None

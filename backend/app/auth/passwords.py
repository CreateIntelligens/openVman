"""bcrypt password hashing without its silent 72-byte truncation."""

from __future__ import annotations

import os

import bcrypt

_MIN_PASSWORD_BYTES = 8
_MAX_PASSWORD_BYTES = 72


class PasswordValidationError(ValueError):
    pass


def validate_password(password: str) -> bytes:
    if not isinstance(password, str):
        raise PasswordValidationError("password must be a string")
    encoded = password.encode("utf-8")
    if len(encoded) < _MIN_PASSWORD_BYTES:
        raise PasswordValidationError(
            f"password must contain at least {_MIN_PASSWORD_BYTES} UTF-8 bytes"
        )
    if len(encoded) > _MAX_PASSWORD_BYTES:
        raise PasswordValidationError(
            f"password must contain at most {_MAX_PASSWORD_BYTES} UTF-8 bytes"
        )
    return encoded


_DEFAULT_ROUNDS = 12
_MIN_ROUNDS = 4


def _rounds() -> int:
    """bcrypt cost factor; AUTH_BCRYPT_ROUNDS overrides the default 12.

    一次雜湊約 0.3 秒是正式環境要的；測試一跑就建上百個帳號、登入上百次，
    光這個就吃掉幾分鐘，所以單元測試把它降到 4。驗證照存起來的雜湊自己的
    cost 走，改這個值不影響既有密碼。
    """
    raw = os.getenv("AUTH_BCRYPT_ROUNDS", "").strip()
    if not raw:
        return _DEFAULT_ROUNDS
    try:
        return max(_MIN_ROUNDS, int(raw))
    except ValueError:
        return _DEFAULT_ROUNDS


def hash_password(password: str) -> str:
    encoded = validate_password(password)
    return bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=_rounds())).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        if not isinstance(password, str) or not password:
            return False
        encoded = password.encode("utf-8")
        if len(encoded) > _MAX_PASSWORD_BYTES:
            return False
        return bcrypt.checkpw(encoded, password_hash.encode("utf-8"))
    except (AttributeError, TypeError, UnicodeEncodeError, ValueError):
        return False

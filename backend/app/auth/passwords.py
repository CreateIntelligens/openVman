"""bcrypt password hashing without its silent 72-byte truncation."""

from __future__ import annotations

import bcrypt

_MIN_PASSWORD_BYTES = 4
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


def hash_password(password: str) -> str:
    encoded = validate_password(password)
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        encoded = validate_password(password)
        return bcrypt.checkpw(encoded, password_hash.encode("utf-8"))
    except (PasswordValidationError, TypeError, ValueError):
        return False

"""Recoverable temporary passwords remain authenticated and account-bound."""

import pytest

from app.auth.temporary_passwords import TemporaryPasswordCipher

_SECRET = "temporary-password-test-key-" * 2
_PASSWORD = "AccountCode1Password2"  # gitleaks:allow
_LOCATOR = _PASSWORD[:12]


def test_password_cipher_roundtrip_survives_reconstruction():
    cipher = TemporaryPasswordCipher(_SECRET)
    ciphertext = cipher.encrypt(_PASSWORD, _LOCATOR)

    assert _PASSWORD not in ciphertext
    assert _LOCATOR not in ciphertext
    assert TemporaryPasswordCipher(_SECRET).decrypt(
        ciphertext, _LOCATOR,
    ) == _PASSWORD
    assert cipher.encrypt(_PASSWORD, _LOCATOR) != ciphertext


def test_ciphertext_cannot_be_used_with_another_account_or_key():
    ciphertext = TemporaryPasswordCipher(_SECRET).encrypt(_PASSWORD, _LOCATOR)

    assert TemporaryPasswordCipher(_SECRET).decrypt(
        ciphertext, "other-locator",
    ) is None
    assert TemporaryPasswordCipher("another-test-key-" * 3).decrypt(
        ciphertext, _LOCATOR,
    ) is None


@pytest.mark.parametrize("ciphertext", [None, "", "not-fernet", "☃"])
def test_missing_or_malformed_ciphertext_returns_none(ciphertext):
    assert TemporaryPasswordCipher(_SECRET).decrypt(
        ciphertext, _LOCATOR,
    ) is None


def test_tampering_returns_none():
    cipher = TemporaryPasswordCipher(_SECRET)
    ciphertext = cipher.encrypt(_PASSWORD, _LOCATOR)
    replacement = "A" if ciphertext[20] != "A" else "B"
    tampered = ciphertext[:20] + replacement + ciphertext[21:]

    assert cipher.decrypt(tampered, _LOCATOR) is None


@pytest.mark.parametrize("secret", ["", "x" * 31, "密" * 10])
def test_secret_requires_at_least_32_utf8_bytes(secret):
    with pytest.raises(ValueError):
        TemporaryPasswordCipher(secret)


def test_multibyte_secret_meets_byte_length_requirement():
    cipher = TemporaryPasswordCipher("密" * 11)
    ciphertext = cipher.encrypt(_PASSWORD, _LOCATOR)

    assert cipher.decrypt(ciphertext, _LOCATOR) == _PASSWORD

"""bcrypt 的 cost 要能由環境變數降下來，否則整套 auth 測試慢到沒人想跑。"""

from __future__ import annotations

import bcrypt
import pytest

from app.auth.passwords import hash_password, verify_password


def _cost(password_hash: str) -> int:
    # bcrypt 雜湊長 $2b$<cost>$...，cost 固定兩位數。
    return int(password_hash.split("$")[2])


def test_unit_tests_hash_with_the_cheap_cost_from_conftest() -> None:
    digest = hash_password("correct horse battery")
    assert _cost(digest) == 4
    assert verify_password("correct horse battery", digest)
    assert not verify_password("wrong horse", digest)


def test_default_cost_stays_at_twelve_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTH_BCRYPT_ROUNDS", raising=False)
    # 不真的算 12 rounds（0.3 秒），只確認會把 12 交給 gensalt。
    seen: dict[str, int] = {}
    real_gensalt = bcrypt.gensalt

    def fake_gensalt(rounds: int = 12) -> bytes:
        seen["rounds"] = rounds
        return real_gensalt(rounds=4)

    monkeypatch.setattr(bcrypt, "gensalt", fake_gensalt)
    hash_password("correct horse battery")
    assert seen["rounds"] == 12


def test_cost_outside_bcrypt_range_is_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_BCRYPT_ROUNDS", "1")
    assert _cost(hash_password("correct horse battery")) == 4
    monkeypatch.setenv("AUTH_BCRYPT_ROUNDS", "99")
    seen_max: dict[str, int] = {}
    real = bcrypt.gensalt

    def fake_max(rounds: int = 12) -> bytes:
        seen_max["rounds"] = rounds
        return real(rounds=4)

    monkeypatch.setattr(bcrypt, "gensalt", fake_max)
    hash_password("correct horse battery")
    assert seen_max["rounds"] == 31
    monkeypatch.setattr(bcrypt, "gensalt", real)
    monkeypatch.setenv("AUTH_BCRYPT_ROUNDS", "not-a-number")
    seen: dict[str, int] = {}
    real_gensalt = bcrypt.gensalt

    def fake_gensalt(rounds: int = 12) -> bytes:
        seen["rounds"] = rounds
        return real_gensalt(rounds=4)

    monkeypatch.setattr(bcrypt, "gensalt", fake_gensalt)
    hash_password("correct horse battery")
    assert seen["rounds"] == 12

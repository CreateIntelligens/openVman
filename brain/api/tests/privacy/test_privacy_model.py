"""Tests for Privacy Filter masking behavior."""

from __future__ import annotations

import pytest

from privacy.model import detect_and_mask


@pytest.mark.parametrize(
    ("text", "category", "raw_value"),
    [
        ("My name is Jane Doe.", "private_person", "Jane Doe"),
        ("Ship it to 123 Main St.", "private_address", "123 Main St"),
        ("Email me at jane@example.com.", "private_email", "jane@example.com"),
        ("Call 0912345678 tomorrow.", "private_phone", "0912345678"),
        ("Private host is 10.0.0.42.", "private_url", "10.0.0.42"),
        ("Birthday is 1990-01-02.", "private_date", "1990-01-02"),
        ("Account number 123456789012 is active.", "account_number", "123456789012"),
        ("password=super-secret", "secret", "super-secret"),
    ],
)
def test_detect_and_mask_known_pii_categories(text: str, category: str, raw_value: str) -> None:
    masked, counts = detect_and_mask(text)

    assert raw_value not in masked
    assert f"[REDACTED:{category}]" in masked
    assert counts[category] >= 1



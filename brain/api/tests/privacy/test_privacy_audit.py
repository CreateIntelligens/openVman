"""Tests for typed privacy audit events."""

from __future__ import annotations

from dataclasses import fields

import pytest

from privacy.audit import PrivacyFilterAuditEvent, record_privacy_filter_event


def test_audit_event_has_no_raw_content_fields() -> None:
    event_fields = {field.name for field in fields(PrivacyFilterAuditEvent)}

    assert event_fields == {"action", "source", "categories", "counts", "trace_id"}
    assert event_fields.isdisjoint({"content", "text", "message", "raw_text", "masked_text"})


def test_audit_event_rejects_content_field() -> None:
    with pytest.raises(TypeError):
        PrivacyFilterAuditEvent(
            action="masked",
            source="chat",
            categories=("private_phone",),
            counts={"private_phone": 1},
            trace_id="t1",
            content="0912345678",
        )


def test_record_privacy_filter_event_requires_typed_event() -> None:
    with pytest.raises(TypeError):
        record_privacy_filter_event("masked")

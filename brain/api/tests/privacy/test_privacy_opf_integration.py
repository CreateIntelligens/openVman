"""OPF model integration tests.

These tests load the *real* OPF model and verify behaviour that the regex-stub
unit tests cannot cover:

- Chinese name / phone detection (OPF NER vs. regex heuristics)
- Span boundary accuracy (OPF-reported offsets must match the original text)
- Label mapping: OPF labels are members of ``PII_CATEGORIES``
- No false positives on benign Chinese prose

Run:   pytest -m integration
Skip:  pytest -m "not integration"   (default in CI fast pass)
"""

from __future__ import annotations

import pytest

from privacy.model import (
    PII_CATEGORIES,
    detect_and_mask,
    load_privacy_filter_model_cpu,
)


# ---------------------------------------------------------------------------
# Module-scoped fixture: load OPF once for the whole file
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def opf_model():
    """Load OPF on CPU for the entire module; reset global state after."""
    import privacy.model as _m

    load_privacy_filter_model_cpu()
    yield
    # Reset so later tests start with a clean slate.
    _m._opf = None
    _m._runtime_disabled_reason = None
    _m._regex_fallback_for_tests = False


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _detected_categories(text: str) -> set[str]:
    _, counts = detect_and_mask(text)
    return set(counts)


def _is_masked(original: str, raw_value: str) -> bool:
    masked, _ = detect_and_mask(original)
    return raw_value not in masked


# ---------------------------------------------------------------------------
# English PII detection
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_opf_detects_english_email() -> None:
    text = "Reach me at alice@example.com for questions."
    assert _is_masked(text, "alice@example.com"), "OPF should mask the email address"
    assert "private_email" in _detected_categories(text)


@pytest.mark.integration
def test_opf_detects_english_phone() -> None:
    text = "Call me at +1 650-555-0123 anytime."
    masked, counts = detect_and_mask(text)
    assert "+1 650-555-0123" not in masked, "OPF should mask the phone number"
    assert "private_phone" in counts


@pytest.mark.integration
def test_opf_detects_english_person_name() -> None:
    text = "My name is Robert Johnson and I live in Seattle."
    assert _is_masked(text, "Robert Johnson"), "OPF should mask the person's name"
    assert "private_person" in _detected_categories(text)


@pytest.mark.integration
def test_opf_detects_credential_secret() -> None:
    text = "token=ghp_abc123XYZ456secret789token00"
    masked, counts = detect_and_mask(text)
    assert "ghp_abc123XYZ456secret789token00" not in masked
    assert counts  # at least one category detected


# ---------------------------------------------------------------------------
# Chinese PII detection (the key gap vs. regex-stub)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_opf_detects_chinese_embedded_email() -> None:
    """OPF should detect an email address embedded in Chinese prose."""
    text = "請聯絡 alice@company.org 以獲得更多資訊。"
    assert _is_masked(text, "alice@company.org"), "Email in Chinese sentence should be masked"
    assert "private_email" in _detected_categories(text)


@pytest.mark.integration
def test_opf_detects_chinese_phone_number() -> None:
    """OPF should detect a Taiwanese mobile number in a Chinese sentence."""
    text = "我的手機號碼是 0912-345-678，請來電。"
    masked, counts = detect_and_mask(text)
    assert "0912-345-678" not in masked, "Phone number in Chinese text should be masked"
    assert counts  # at least one PII category


@pytest.mark.integration
def test_opf_no_false_positive_on_benign_chinese() -> None:
    """Ordinary Chinese prose should not trigger any PII detection."""
    text = "今天天氣很好，我們去公園散步吧。"
    _, counts = detect_and_mask(text)
    assert not counts, f"Benign Chinese text should have zero PII counts, got: {counts}"


@pytest.mark.integration
@pytest.mark.parametrize("text", [
    "你的名字?",
    "我的號碼?",
    "我的電話?",
    "你叫什麼?",
    "他是誰?",
])
def test_opf_no_false_positive_on_short_chinese_questions(text: str) -> None:
    """Short Chinese questions referencing PII concepts must not be flagged.

    Regression: previously these triggered ``private_phone`` because the OPF
    model was sensitive to keywords like 號碼 / 電話 even when no actual
    number was present.
    """
    _, counts = detect_and_mask(text)
    assert not counts, f"Short Chinese question {text!r} should have no PII, got: {counts}"


# ---------------------------------------------------------------------------
# Span boundary accuracy
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.parametrize("text,expected_raw", [
    ("Email bob@example.org for info.", "bob@example.org"),
    ("Call +886 912 345 678 please.", "+886 912 345 678"),
])
def test_opf_span_boundaries_match_original_text(text: str, expected_raw: str) -> None:
    """OPF-reported spans must correspond to the actual PII substring in the input."""
    import privacy.model as _m

    assert _m._opf is not None, "OPF model must be loaded for this test"
    result = _m._opf.redact(text)

    pii_spans = [s for s in result.detected_spans if s.label in PII_CATEGORIES]
    assert pii_spans, f"Expected at least one PII span in: {text!r}"

    extracted_values = [text[s.start:s.end] for s in pii_spans]
    for span, extracted in zip(pii_spans, extracted_values, strict=True):
        assert span.start < span.end, "Span start must be before end"
        assert extracted, f"Span [{span.start}:{span.end}] yields empty string in {text!r}"
    assert any(expected_raw in v or v in expected_raw for v in extracted_values), (
        f"Expected raw value {expected_raw!r} to appear in detected spans, got {extracted_values}"
    )


# ---------------------------------------------------------------------------
# Label mapping: all returned labels must be known categories
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_opf_labels_are_subset_of_known_categories() -> None:
    """Every label OPF returns for PII must be a member of PII_CATEGORIES."""
    import privacy.model as _m

    assert _m._opf is not None
    samples = [
        "Contact jane.doe@corp.io tomorrow.",
        "Account 9876543210 was charged.",
        "My name is Chen Wei, call 0933-111-222.",
    ]
    for text in samples:
        result = _m._opf.redact(text)
        for span in result.detected_spans:
            assert span.label in PII_CATEGORIES, (
                f"OPF returned label {span.label!r} which is not in PII_CATEGORIES — "
                "either add it to PII_CATEGORIES or verify it is intentionally ignored"
            )

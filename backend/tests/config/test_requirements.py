"""Tests for backend dependency expectations."""

from __future__ import annotations

from pathlib import Path


def test_markitdown_pdf_extra_is_enabled():
    requirements_path = Path(__file__).resolve().parents[1] / "requirements.txt"
    requirements = requirements_path.read_text(encoding="utf-8").splitlines()
    markitdown_line = next(
        line.strip()
        for line in requirements
        if line.strip().startswith("markitdown")
    )

    assert "[pdf]" in markitdown_line or "[all]" in markitdown_line


def test_chardet_is_capped_for_requests_compatibility():
    requirements_path = Path(__file__).resolve().parents[1] / "requirements.txt"
    requirements = requirements_path.read_text(encoding="utf-8").splitlines()

    assert any(line.strip().startswith("chardet<6") for line in requirements)

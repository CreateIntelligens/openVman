"""Tests for backend dependency expectations."""

from __future__ import annotations

from pathlib import Path


def test_markitdown_pdf_extra_is_enabled():
    # markitdown is pinned in the Dockerfile (its own cache layer), not requirements.txt.
    dockerfile_path = Path(__file__).resolve().parents[2] / "Dockerfile"
    markitdown_lines = [
        line.strip()
        for line in dockerfile_path.read_text(encoding="utf-8").splitlines()
        if "markitdown" in line.lower()
    ]

    assert markitdown_lines, "markitdown not pinned in backend/Dockerfile"
    assert any(
        "[pdf]" in line or "[all]" in line for line in markitdown_lines
    ), f"markitdown pinned without [pdf]/[all] extra: {markitdown_lines}"


def test_chardet_is_capped_for_requests_compatibility():
    requirements_path = Path(__file__).resolve().parents[2] / "requirements.txt"
    requirements = requirements_path.read_text(encoding="utf-8").splitlines()

    assert any(line.strip().startswith("chardet<6") for line in requirements)

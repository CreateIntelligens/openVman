"""Tests for backend dependency expectations."""

from __future__ import annotations

from pathlib import Path

_PDF_INSPECTOR_PIN = (
    "git+https://github.com/firecrawl/pdf-inspector.git"
    "@8b63ceb084f75dfd4425129d1d90d5bca45054e4"
)


def _backend_file(name: str) -> Path:
    return Path(__file__).resolve().parents[2] / name


def _dockerfile_text() -> str:
    return _backend_file("Dockerfile").read_text(encoding="utf-8").lower()


def test_markitdown_pdf_extra_is_enabled():
    # markitdown is pinned in the Dockerfile (its own cache layer), not requirements.txt.
    markitdown_lines = [
        line.strip()
        for line in _dockerfile_text().splitlines()
        if "markitdown" in line.lower()
    ]

    assert markitdown_lines, "markitdown not pinned in backend/Dockerfile"
    assert any(
        "[pdf]" in line or "[all]" in line for line in markitdown_lines
    ), f"markitdown pinned without [pdf]/[all] extra: {markitdown_lines}"


def test_pdf_inspector_is_installed_with_rust_build_dependencies():
    dockerfile = _dockerfile_text()

    assert "pdf-inspector" in dockerfile
    assert _PDF_INSPECTOR_PIN in dockerfile
    assert "rustup.rs" in dockerfile
    assert "1.88.0" in dockerfile
    assert "cargo" in dockerfile
    assert "rustc" in dockerfile


def test_chardet_is_capped_for_requests_compatibility():
    requirements = (
        _backend_file("requirements.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    )

    assert any(line.strip().startswith("chardet<6") for line in requirements)


def test_pdf_repair_tools_in_dockerfile():
    dockerfile = _dockerfile_text()

    assert "qpdf" in dockerfile
    assert "mupdf-tools" in dockerfile
    assert "ghostscript" in dockerfile

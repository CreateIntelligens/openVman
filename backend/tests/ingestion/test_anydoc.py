import sys
from pathlib import Path

import pytest


def _anydoc_is_real() -> bool:
    """Return whether AnyDoc is installed rather than stubbed by conftest."""
    module = sys.modules.get("anydoc")
    return getattr(module, "__file__", None) is not None


pytestmark = pytest.mark.skipif(
    not _anydoc_is_real(),
    reason="anydoc is stubbed in test env",
)


def test_csv_conversion_returns_structured_markdown(tmp_path: Path):
    import anydoc

    csv_path = tmp_path / "sample.csv"
    csv_path.write_bytes(b"name,count\nalpha,3\nbeta,7\n")

    markdown = anydoc.to_markdown(csv_path)

    assert "alpha" in markdown
    assert "beta" in markdown
    assert "3" in markdown
    assert "7" in markdown


def test_rtf_conversion_preserves_text(tmp_path: Path):
    import anydoc

    rtf_path = tmp_path / "sample.rtf"
    rtf_path.write_bytes(b"{\\rtf1\\ansi AnyDoc conversion test}")

    markdown = anydoc.to_markdown(rtf_path)

    assert "AnyDoc conversion test" in markdown

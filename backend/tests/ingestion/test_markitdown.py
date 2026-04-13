"""Tests for MarkItDown document conversion integration."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest


def _markitdown_is_real() -> bool:
    """Return True if markitdown is a real module (not the conftest MagicMock stub)."""
    mod = sys.modules.get("markitdown")
    if mod is None:
        return False
    return hasattr(mod, "__file__") and mod.__file__ is not None


@unittest.skipUnless(_markitdown_is_real(), "markitdown is stubbed in test env")
class TestMarkItDown(unittest.TestCase):
    def test_basic_conversion(self):
        from markitdown import MarkItDown

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            tmp.write(b"Hello MarkItDown!")
            tmp_path = tmp.name

        try:
            md = MarkItDown()
            result = md.convert(tmp_path)
            self.assertIn("Hello MarkItDown!", result.text_content)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_markdown_output_format(self):
        from markitdown import MarkItDown

        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as tmp:
            tmp.write(b"# Title\nContent")
            tmp_path = tmp.name

        try:
            md = MarkItDown()
            result = md.convert(tmp_path)
            self.assertEqual(result.text_content.strip(), "# Title\nContent")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

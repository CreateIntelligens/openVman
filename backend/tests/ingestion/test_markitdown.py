import unittest
import os
import tempfile
from markitdown import MarkItDown

class TestMarkItDown(unittest.TestCase):
    def test_basic_conversion(self):
        # Create a temporary text file
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
        # Verify the format expected by our API
        md = MarkItDown()
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as tmp:
            tmp.write(b"# Title\nContent")
            tmp_path = tmp.name
            
        try:
            result = md.convert(tmp_path)
            # The API returns result.text_content as "markdown"
            self.assertEqual(result.text_content.strip(), "# Title\nContent")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

if __name__ == "__main__":
    unittest.main()

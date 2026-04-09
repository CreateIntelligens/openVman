import unittest
from app.utils.chunker import PunctuationChunker

class TestTTSPipeline(unittest.TestCase):
    def test_chunk_text_chinese(self):
        chunker = PunctuationChunker()
        text = "這是一個測試，這是一個好測試。你覺得呢？"
        chunks = list(chunker.split(text))
        self.assertEqual(chunks, ["這是一個測試，", "這是一個好測試。", "你覺得呢？"])

    def test_chunk_text_english(self):
        chunker = PunctuationChunker()
        text = "Hello, world! How are you today?"
        chunks = list(chunker.split(text))
        self.assertEqual(chunks, ["Hello, ", "world! ", "How are you today?"])

    def test_chunk_text_no_punctuation(self):
        chunker = PunctuationChunker()
        text = "這是一段沒有標點的文字"
        chunks = list(chunker.split(text))
        self.assertEqual(chunks, ["這是一段沒有標點的文字"])

    def test_chunk_text_mixed_punctuation(self):
        chunker = PunctuationChunker()
        text = "測試! 真的嗎? 是的; 結束."
        chunks = list(chunker.split(text))
        self.assertEqual(chunks, ["測試! ", "真的嗎? ", "是的; ", "結束."])

if __name__ == "__main__":
    unittest.main()

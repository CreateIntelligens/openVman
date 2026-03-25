import re
from typing import List, Generator


class PunctuationChunker:
    """Chunks text based on punctuation for natural pauses in TTS."""

    def __init__(self, punctuations: str = r"，。？！；,.\?\!;"):
        # Pattern matches one or more non-punctuation characters, 
        # followed by one or more punctuation characters,
        # followed by any optional whitespace.
        self.pattern = re.compile(f"([^{punctuations}]+[{punctuations}]+[\s]*)")

    def split(self, text: str) -> Generator[str, None, None]:
        """Split text into chunks based on punctuation."""
        last_match_end = 0
        for match in self.pattern.finditer(text):
            last_match_end = match.end()
            yield match.group(0)
            
        # Yield any remaining text if it doesn't end with punctuation
        remaining = text[last_match_end:].strip()
        if remaining:
            yield remaining

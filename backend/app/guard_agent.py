import logging
from typing import Literal

logger = logging.getLogger("backend")

class GuardAgent:
    """Classifies user input to decide if it should interrupt the current stream."""

    def __init__(self, model: str = "lightweight"):
        self.model = model
        # Basic keywords that usually indicate a real question or instruction
        self.stop_keywords = ["請問", "為什麼", "如何", "等一下", "不對", "停", "stop", "wait"]

    async def classify(self, text: str) -> Literal["STOP", "IGNORE"]:
        """
        Classify the input text. 
        Returns "STOP" if it's a valid interruption, "IGNORE" if it's likely noise.
        """
        if not text:
            return "IGNORE"

        # Rule 1: Length check (Very short inputs are often filler words like "oh", "um")
        if len(text.strip()) <= 1:
            return "IGNORE"

        # Rule 2: Keyword check
        text_lower = text.lower()
        if any(kw in text_lower for kw in self.stop_keywords):
            return "STOP"

        # Rule 3: Placeholder for LLM-based classification
        # In a real scenario, we would call a cheap LLM here
        # For now, if it's longer than a few words, we assume it's intentional
        if len(text.strip()) > 5:
            return "STOP"

        return "IGNORE"

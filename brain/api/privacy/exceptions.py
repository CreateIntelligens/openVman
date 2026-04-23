"""Privacy filter exceptions."""

from __future__ import annotations


class PrivacyViolationError(RuntimeError):
    """Raised when configured privacy policy blocks an outbound LLM call."""

    def __init__(self, category: str, source: str) -> None:
        super().__init__(f"privacy filter blocked {category} from {source}")
        self.category = category
        self.source = source

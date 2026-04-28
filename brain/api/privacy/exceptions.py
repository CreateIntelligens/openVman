"""Privacy filter exceptions."""

from __future__ import annotations


class PrivacyViolationError(ValueError):
    """Raised when configured privacy policy blocks an outbound LLM call.

    Extends ValueError so chat route handlers surface it as a 400-class user
    error rather than a 500, since the trigger is bad user input.
    """

    def __init__(self, category: str, source: str) -> None:
        super().__init__(f"privacy filter blocked {category} from {source}")
        self.category = category
        self.source = source

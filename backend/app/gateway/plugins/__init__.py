"""Plugin system — IPlugin protocol and registry."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class IPlugin(Protocol):
    """Contract for all gateway plugins."""

    id: str

    async def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        """Run the plugin's main action."""
        ...

    async def health_check(self) -> bool:
        """Return True if the plugin is healthy."""
        ...

    async def cleanup(self, session_id: str) -> None:
        """Release resources tied to a session."""
        ...

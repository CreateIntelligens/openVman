"""Shared httpx singleton client factory — eliminates boilerplate across modules."""

from __future__ import annotations

import httpx


class SharedAsyncClient:
    """Lazy singleton wrapper for httpx.AsyncClient.

    Usage::

        _http = SharedAsyncClient(read=30, follow_redirects=True)

        async def do_request():
            client = _http.get()
            resp = await client.get(...)

        # on shutdown
        await _http.close()
    """

    def __init__(
        self,
        *,
        connect: float = 5,
        read: float = 10,
        write: float = 10,
        pool: float = 5,
        follow_redirects: bool = False,
    ) -> None:
        self._timeout = httpx.Timeout(connect=connect, read=read, write=write, pool=pool)
        self._follow_redirects = follow_redirects
        self._client: httpx.AsyncClient | None = None

    def get(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=self._follow_redirects,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class SharedSyncClient:
    """Lazy singleton wrapper for httpx.Client (synchronous)."""

    def __init__(
        self,
        *,
        connect: float = 5,
        read: float = 10,
        write: float = 10,
        pool: float = 5,
        follow_redirects: bool = False,
    ) -> None:
        self._timeout = httpx.Timeout(connect=connect, read=read, write=write, pool=pool)
        self._follow_redirects = follow_redirects
        self._client: httpx.Client | None = None

    def get(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=self._timeout,
                follow_redirects=self._follow_redirects,
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

"""Async HTTP client for the OpenViking context database."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import OPENVIKING_URL

logger = logging.getLogger(__name__)

_client: OpenVikingClient | None = None


class OpenVikingClient:
    """Thin async wrapper around the OpenViking HTTP API."""

    def __init__(self, base_url: str = OPENVIKING_URL) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(10.0, connect=5.0),
        )

    async def close(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health(self) -> bool:
        try:
            resp = await self._http.get("/health")
            return resp.status_code == 200  # noqa: PLR2004
        except httpx.HTTPError:
            logger.warning("OpenViking health check failed", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def create_session(self, session_id: str) -> dict[str, Any] | None:
        return await self._post(
            "/api/v1/sessions",
            json={"session_id": session_id, "auto_create": True},
        )

    async def add_message(
        self,
        session_id: str,
        role: str,
        text: str,
    ) -> dict[str, Any] | None:
        return await self._post(
            f"/api/v1/sessions/{session_id}/messages",
            json={"role": role, "parts": [{"type": "text", "text": text}]},
        )

    async def commit_session(
        self,
        session_id: str,
        *,
        wait: bool = False,
    ) -> dict[str, Any] | None:
        url = f"/api/v1/sessions/{session_id}/commit"
        if wait:
            url += "?wait=true"
        return await self._post(url)

    # ------------------------------------------------------------------
    # Memory operations
    # ------------------------------------------------------------------

    async def find(
        self,
        query: str,
        *,
        namespaces: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {"query": query, "limit": limit}
        if namespaces:
            body["namespaces"] = namespaces
        result = await self._post("/api/v1/find", json=body)
        if result is None:
            return []
        return result.get("results", result.get("memories", []))

    async def store_memory(self, uri: str, content: str) -> dict[str, Any] | None:
        return await self._post(
            "/api/v1/resources",
            json={"uri": uri, "content": content},
        )

    async def delete_memory(self, uri: str) -> bool:
        try:
            resp = await self._http.request("DELETE", f"/api/v1/resources/{uri}")
            return resp.is_success
        except httpx.HTTPError:
            logger.warning("OpenViking delete failed for %s", uri, exc_info=True)
            return False

    async def ls(self, uri: str) -> list[dict[str, Any]]:
        result = await self._post("/api/v1/ls", json={"uri": uri})
        if result is None:
            return []
        return result.get("entries", result.get("resources", []))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _post(
        self,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        try:
            resp = await self._http.post(path, json=json)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError:
            logger.warning("OpenViking request failed: POST %s", path, exc_info=True)
            return None


def get_client() -> OpenVikingClient:
    """Return a module-level singleton client."""
    global _client  # noqa: PLW0603
    if _client is None:
        _client = OpenVikingClient()
    return _client

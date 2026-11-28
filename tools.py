"""Agent-facing memory tools for the OpenViking plugin."""

from __future__ import annotations

import json
import uuid
from typing import Literal

from mindroom.plugin_api import (
    SetupType,
    ToolCategory,
    ToolFileAccess,
    Toolkit,
    ToolStatus,
    get_logger,
    register_tool_with_metadata,
    tool,
)

from .client import get_client

logger = get_logger(__name__)

_ALLOWED_ACTION_PARAMS: dict[str, frozenset[str]] = {
    "recall": frozenset({"query"}),
    "store": frozenset({"content", "category"}),
    "forget": frozenset({"query"}),
}


def _payload(status: str, **kwargs: object) -> str:
    data: dict[str, object] = {"status": status, "tool": "openviking"}
    data.update(kwargs)
    return json.dumps(data, sort_keys=True)


def _validate_openviking_params(
    action: str,
    *,
    query: object,
    content: object,
    category: object,
) -> str | None:
    """Validate required and allowed parameters for a valid ``action``."""
    allowed = _ALLOWED_ACTION_PARAMS[action]
    provided = (
        ("query", query),
        ("content", content),
        ("category", category),
    )
    unexpected = [name for name, value in provided if value is not None and name not in allowed]
    if unexpected:
        names = ", ".join(unexpected)
        return f"Parameter(s) {names} cannot be used with action={action!r}."

    if action in {"recall", "forget"}:
        if not isinstance(query, str) or not query.strip():
            return f"Query must be a non-empty string for action={action!r}."
    elif action == "store":
        if not isinstance(content, str) or not content.strip():
            return "Content must be a non-empty string for action='store'."
        if category is not None and (not isinstance(category, str) or not category.strip()):
            return "Category must be a non-empty string when provided for action='store'."

    return None


class OpenVikingMemoryTools(Toolkit):
    """Toolkit for explicit OpenViking memory operations."""

    offer_background_after = False
    offer_output_path = False

    def __init__(self) -> None:
        super().__init__(
            name="openviking",
            instructions="Use `openviking` to recall, store, or forget long-term memories in OpenViking.",
        )
        logger.debug("Registered OpenViking memory tools")

    @tool
    async def openviking(
        self,
        action: Literal["recall", "store", "forget"],
        query: str | None = None,
        content: str | None = None,
        category: str | None = None,
    ) -> str:
        """Recall, store, or forget OpenViking long-term memories (only pass args for `action`).

        - `recall`: search by `query`.
        - `store`: save `content`.
        - `forget`: delete matches for `query`.

        Args:
            action: Operation to run.
            query: Search query (`recall`/`forget`).
            content: Memory text (`store`).
            category: Optional label (`store`, default `"general"`; ignored by session-commit storage).
        """
        if not isinstance(action, str) or action not in _ALLOWED_ACTION_PARAMS:
            return _payload("error", message="Unsupported action. Expected one of: recall, store, forget.")

        if error := _validate_openviking_params(action, query=query, content=content, category=category):
            return _payload("error", action=action, message=error)

        if action == "recall":
            assert isinstance(query, str)
            return await self._recall(query)
        if action == "store":
            assert isinstance(content, str)
            assert category is None or isinstance(category, str)
            return await self._store(content, category=category)
        assert isinstance(query, str)
        return await self._forget(query)

    async def _recall(self, query: str) -> str:
        client = get_client()
        try:
            results = await client.find(query.strip(), namespaces=["user", "agent"], limit=10)
        except Exception:  # noqa: BLE001
            return _payload("error", action="recall", message="Failed to search memories")

        if not results:
            return _payload("ok", action="recall", results=[], message="No memories found")

        formatted = [
            {
                "uri": mem.get("uri", ""),
                "content": mem.get("content", mem.get("text", "")),
            }
            for mem in results
        ]
        return _payload("ok", action="recall", results=formatted)

    async def _store(self, content: str, *, category: str | None) -> str:
        client = get_client()
        resolved_category = "general" if category is None else category.strip()
        memory_id = uuid.uuid4().hex[:12]
        uri = f"viking://user/memories/{resolved_category}/{memory_id}"

        try:
            result = await client.store_memory(uri, content.strip())
        except Exception:  # noqa: BLE001
            return _payload("error", action="store", message="Failed to store memory")

        if result is None:
            return _payload("error", action="store", message="Failed to store memory")

        return _payload(
            "ok",
            action="store",
            session_id=result.get("session_id", ""),
            uri=result.get("archive_uri", uri),
        )

    async def _forget(self, query: str) -> str:
        client = get_client()
        try:
            results = await client.find(query.strip(), namespaces=["user", "agent"], limit=10)
        except Exception:  # noqa: BLE001
            return _payload("error", action="forget", message="Failed to search memories")

        if not results:
            return _payload("ok", action="forget", deleted=[], message="No matching memories found")

        deleted: list[str] = []
        failed: list[str] = []
        for mem in results:
            uri = mem.get("uri", "")
            if not uri:
                continue
            if await client.delete_memory(uri):
                deleted.append(uri)
            else:
                failed.append(uri)

        return _payload("ok", action="forget", deleted=deleted, failed=failed)


@register_tool_with_metadata(
    name="openviking",
    file_access=ToolFileAccess.NONE,
    display_name="OpenViking Memory",
    description="Search, store, and delete long-term memories in OpenViking.",
    category=ToolCategory.PRODUCTIVITY,
    status=ToolStatus.AVAILABLE,
    setup_type=SetupType.NONE,
    action_scoped_grants=("openviking",),
    retired_functions={
        "memory_recall": "openviking",
        "memory_store": "openviking",
        "memory_forget": "openviking",
    },
)
def openviking_factory() -> type[OpenVikingMemoryTools]:
    """Factory function for the OpenViking memory toolkit."""
    return OpenVikingMemoryTools


__all__ = [
    "OpenVikingMemoryTools",
    "openviking_factory",
]

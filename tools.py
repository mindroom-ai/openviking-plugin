"""Agent-facing memory tools for the OpenViking plugin."""

from __future__ import annotations

import json
import uuid

from agno.tools import Toolkit, tool
from agno.utils.log import logger
from mindroom.tool_system.metadata import (
    SetupType,
    ToolCategory,
    ToolStatus,
    register_tool_with_metadata,
)

from .client import get_client


def _payload(status: str, **kwargs: object) -> str:
    data: dict[str, object] = {"status": status, "tool": "openviking"}
    data.update(kwargs)
    return json.dumps(data, sort_keys=True)


class OpenVikingMemoryTools(Toolkit):
    """Toolkit for explicit OpenViking memory operations."""

    def __init__(self) -> None:
        super().__init__(
            name="openviking",
            instructions=(
                "Use these tools to search, store, and delete long-term memories in OpenViking."
            ),
            tools=[],
        )
        self.register(self.memory_recall)
        self.register(self.memory_store)
        self.register(self.memory_forget)
        logger.debug("Registered OpenViking memory tools")

    @tool(name="memory_recall", description="Search long-term memory for relevant information")
    async def memory_recall(self, query: str) -> str:
        """Search OpenViking for memories matching the query."""
        client = get_client()
        try:
            results = await client.find(query, namespaces=["user", "agent"], limit=10)
        except Exception:
            return _payload("error", message="Failed to search memories")

        if not results:
            return _payload("ok", action="recall", results=[], message="No memories found")

        formatted = []
        for mem in results:
            formatted.append(
                {
                    "uri": mem.get("uri", ""),
                    "content": mem.get("content", mem.get("text", "")),
                }
            )

        return _payload("ok", action="recall", results=formatted)

    @tool(name="memory_store", description="Store a new memory in long-term storage")
    async def memory_store(self, content: str, category: str = "general") -> str:
        """Explicitly store a memory in OpenViking."""
        if not content or not content.strip():
            return _payload("error", message="Content must not be empty")

        client = get_client()
        memory_id = uuid.uuid4().hex[:12]
        uri = f"viking://user/memories/{category}/{memory_id}"

        try:
            result = await client.store_memory(uri, content.strip())
        except Exception:
            return _payload("error", message="Failed to store memory")

        if result is None:
            return _payload("error", message="Failed to store memory")

        return _payload(
            "ok",
            action="store",
            session_id=result.get("session_id", ""),
            uri=result.get("archive_uri", uri),
        )

    @tool(name="memory_forget", description="Find and delete memories matching a query")
    async def memory_forget(self, query: str) -> str:
        """Search for matching memories and delete them."""
        if not query or not query.strip():
            return _payload("error", message="Query must not be empty")

        client = get_client()

        try:
            results = await client.find(query, namespaces=["user", "agent"], limit=10)
        except Exception:
            return _payload("error", message="Failed to search memories")

        if not results:
            return _payload("ok", action="forget", deleted=[], message="No matching memories found")

        deleted: list[str] = []
        failed: list[str] = []
        for mem in results:
            uri = mem.get("uri", "")
            if not uri:
                continue
            success = await client.delete_memory(uri)
            if success:
                deleted.append(uri)
            else:
                failed.append(uri)

        return _payload("ok", action="forget", deleted=deleted, failed=failed)


@register_tool_with_metadata(
    name="openviking",
    display_name="OpenViking Memory",
    description="Search, store, and delete long-term memories in OpenViking.",
    category=ToolCategory.PRODUCTIVITY,
    status=ToolStatus.AVAILABLE,
    setup_type=SetupType.NONE,
)
def openviking_factory() -> type[OpenVikingMemoryTools]:
    """Factory function for the OpenViking memory toolkit."""
    return OpenVikingMemoryTools


def _get_async_entrypoint(tool_name: str):
    toolkit = OpenVikingMemoryTools()
    function = toolkit.get_async_functions()[tool_name]
    return function.entrypoint


async def memory_recall(query: str) -> str:
    """Compatibility wrapper for memory recall."""
    entrypoint = _get_async_entrypoint("memory_recall")
    if entrypoint is None:
        return _payload("error", message="Memory recall tool is unavailable")
    return await entrypoint(query)


async def memory_store(content: str, category: str = "general") -> str:
    """Compatibility wrapper for memory storage."""
    entrypoint = _get_async_entrypoint("memory_store")
    if entrypoint is None:
        return _payload("error", message="Memory store tool is unavailable")
    return await entrypoint(content, category)


async def memory_forget(query: str) -> str:
    """Compatibility wrapper for memory deletion."""
    entrypoint = _get_async_entrypoint("memory_forget")
    if entrypoint is None:
        return _payload("error", message="Memory forget tool is unavailable")
    return await entrypoint(query)


__all__ = [
    "OpenVikingMemoryTools",
    "memory_forget",
    "memory_recall",
    "memory_store",
    "openviking_factory",
]

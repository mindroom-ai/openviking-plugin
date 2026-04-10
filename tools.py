"""Agent-facing memory tools for the OpenViking plugin."""

from __future__ import annotations

import json
import uuid

from mindroom.hooks import tool

from .client import get_client


def _payload(status: str, **kwargs: object) -> str:
    data: dict[str, object] = {"status": status, "tool": "openviking"}
    data.update(kwargs)
    return json.dumps(data, sort_keys=True)


@tool(name="memory_recall", description="Search long-term memory for relevant information")
async def memory_recall(query: str) -> str:
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
        formatted.append({
            "uri": mem.get("uri", ""),
            "content": mem.get("content", mem.get("text", "")),
        })

    return _payload("ok", action="recall", results=formatted)


@tool(name="memory_store", description="Store a new memory in long-term storage")
async def memory_store(content: str, category: str = "general") -> str:
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

    return _payload("ok", action="store", uri=uri)


@tool(name="memory_forget", description="Find and delete memories matching a query")
async def memory_forget(query: str) -> str:
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

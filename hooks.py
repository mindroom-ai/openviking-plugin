"""OpenViking hook functions for the MindRoom plugin system."""

from __future__ import annotations

import asyncio
import logging
import subprocess
from typing import Any

import httpx
from mindroom.hooks import EnrichmentItem, hook

from .client import get_client
from .config import COMMIT_TOKEN_THRESHOLD, OPENVIKING_URL, RECALL_MAX_TOKENS

logger = logging.getLogger(__name__)
_AUTO_START_ATTEMPTED = False


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(text) // 4


def _extract_last_user_text(messages: list[dict[str, Any]]) -> str | None:
    """Extract the text content from the most recent user message."""
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    return part.get("text", "")
                if isinstance(part, str):
                    return part
        break
    return None


def _format_memories(memories: list[dict[str, Any]], max_tokens: int) -> str:
    """Format retrieved memories into a text block, respecting token budget."""
    if not memories:
        return ""
    lines: list[str] = []
    total_tokens = 0
    for mem in memories:
        content = mem.get("content", mem.get("text", ""))
        uri = mem.get("uri", "")
        line = f"- [{uri}] {content}" if uri else f"- {content}"
        line_tokens = _estimate_tokens(line)
        if total_tokens + line_tokens > max_tokens:
            break
        lines.append(line)
        total_tokens += line_tokens
    return "\n".join(lines)


def _extract_text(msg: dict[str, Any]) -> str:
    """Extract plain text from a message dict."""
    content = msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(part.get("text", ""))
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(parts)
    return str(content)


def _session_key(ctx: Any) -> str:
    """Derive a session key from context identifiers."""
    thread = getattr(ctx, "thread_id", None) or "default"
    room = getattr(ctx, "room_id", None) or "global"
    return f"{room}:{thread}"


async def _ensure_server_running() -> None:
    """Start OpenViking once if the configured server is unreachable."""
    global _AUTO_START_ATTEMPTED  # noqa: PLW0603
    timeout = httpx.Timeout(1.0, connect=1.0)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            await client.get(OPENVIKING_URL)
            return
    except httpx.HTTPError:
        if _AUTO_START_ATTEMPTED:
            return
        _AUTO_START_ATTEMPTED = True

    try:
        subprocess.Popen(  # noqa: S603
            ["uvx", "--with", "openviking", "openviking-server"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        logger.warning("Failed to auto-start OpenViking server at %s", OPENVIKING_URL, exc_info=True)
        return

    async with httpx.AsyncClient(timeout=timeout) as client:
        for _ in range(10):
            try:
                await client.get(OPENVIKING_URL)
                return
            except httpx.HTTPError:
                await asyncio.sleep(0.5)

    logger.warning("OpenViking server at %s did not start within 5 seconds", OPENVIKING_URL)


# ------------------------------------------------------------------
# Hooks
# ------------------------------------------------------------------


@hook(
    event="session:started",
    name="openviking-init-session",
    priority=10,
    timeout_ms=5000,
)
async def init_session(ctx: Any) -> None:
    """Initialize an OpenViking session when a new MindRoom session starts."""
    session_id = _session_key(ctx)
    await _ensure_server_running()
    client = get_client()
    result = await client.create_session(session_id)
    if result is None:
        logger.warning("Failed to create OpenViking session %s", session_id)


@hook(
    event="message:enrich",
    name="openviking-recall",
    priority=30,
    timeout_ms=5000,
)
async def recall_memories(ctx: Any) -> list[EnrichmentItem]:
    """Auto-recall relevant memories and inject them before each prompt."""
    messages = getattr(ctx, "messages", [])
    user_text = _extract_last_user_text(messages)
    if not user_text:
        return []

    client = get_client()
    memories = await client.find(user_text, namespaces=["user", "agent"], limit=10)
    if not memories:
        return []

    formatted = _format_memories(memories, max_tokens=RECALL_MAX_TOKENS)
    if not formatted:
        return []

    return [
        EnrichmentItem(
            key="openviking_memories",
            text=f"Relevant memories from long-term storage:\n{formatted}",
            cache_policy="volatile",
        ),
    ]


@hook(
    event="message:after_response",
    name="openviking-archive-turn",
    priority=50,
    timeout_ms=10000,
)
async def archive_turn(ctx: Any) -> None:
    """Archive the latest conversation turn to OpenViking after each response."""
    messages = getattr(ctx, "messages", [])
    if not messages:
        return

    session_id = _session_key(ctx)
    client = get_client()

    # Find the last user and assistant messages to archive
    user_msg: dict[str, Any] | None = None
    assistant_msg: dict[str, Any] | None = None
    for msg in reversed(messages):
        role = msg.get("role")
        if role == "assistant" and assistant_msg is None:
            assistant_msg = msg
        elif role == "user" and user_msg is None:
            user_msg = msg
        if user_msg and assistant_msg:
            break

    if user_msg:
        await client.add_message(session_id, "user", _extract_text(user_msg))
    if assistant_msg:
        await client.add_message(session_id, "assistant", _extract_text(assistant_msg))

    # Commit if accumulated tokens exceed threshold
    total_text = "".join(_extract_text(m) for m in messages)
    if _estimate_tokens(total_text) >= COMMIT_TOKEN_THRESHOLD:
        await client.commit_session(session_id)


@hook(
    event="compaction:before",
    name="openviking-pre-compaction",
    priority=10,
    timeout_ms=30000,
)
async def pre_compaction_archive(ctx: Any) -> None:
    """Archive all messages to OpenViking before MindRoom compacts them away."""
    messages = getattr(ctx, "messages", [])
    if not messages:
        return

    session_id = getattr(ctx, "session_id", None) or _session_key(ctx)
    client = get_client()

    for msg in messages:
        role = msg.get("role")
        if role in ("user", "assistant"):
            await client.add_message(session_id, role, _extract_text(msg))

    # Synchronous commit to ensure nothing is lost before compaction
    await client.commit_session(session_id, wait=True)

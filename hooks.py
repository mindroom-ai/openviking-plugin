"""OpenViking hook functions for the MindRoom plugin system."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from agno.models.message import Message
from mindroom.hooks import (
    AfterResponseContext,
    CompactionHookContext,
    EnrichmentItem,
    MessageEnrichContext,
    SessionHookContext,
    hook,
)

from .client import get_client
from .config import COMMIT_TOKEN_THRESHOLD, OPENVIKING_URL, RECALL_MAX_TOKENS

logger = logging.getLogger(__name__)
_AUTO_START_ATTEMPTED = False
_SESSION_PENDING_TOKENS: dict[str, int] = {}


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(text) // 4


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


def _extract_text(message: Message) -> str:
    """Extract plain text from one Agno message."""
    content = message.content
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
    return "" if content is None else str(content)


def _session_key(room_id: str, thread_id: str | None) -> str:
    """Derive one stable OpenViking session key from a Matrix target."""
    return f"{room_id}:{thread_id or 'default'}"


async def _ensure_server_running() -> None:
    """Warn once if the configured OpenViking server is unreachable."""
    global _AUTO_START_ATTEMPTED  # noqa: PLW0603
    if _AUTO_START_ATTEMPTED:
        return

    timeout = httpx.Timeout(1.0, connect=1.0)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            await client.get(OPENVIKING_URL)
            return
    except httpx.HTTPError:
        _AUTO_START_ATTEMPTED = True
        logger.warning(
            "OpenViking server at %s is not reachable; start it manually before using this plugin",
            OPENVIKING_URL,
            exc_info=True,
        )


# ------------------------------------------------------------------
# Hooks
# ------------------------------------------------------------------


@hook(
    event="session:started",
    name="openviking-init-session",
    priority=10,
    timeout_ms=5000,
)
async def init_session(ctx: SessionHookContext) -> None:
    """Initialize an OpenViking session when a new MindRoom session starts."""
    session_id = _session_key(ctx.room_id, ctx.thread_id)
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
async def recall_memories(ctx: MessageEnrichContext) -> list[EnrichmentItem]:
    """Auto-recall relevant memories and inject them before each prompt."""
    user_text = ctx.envelope.body.strip()
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
async def archive_turn(ctx: AfterResponseContext) -> None:
    """Archive the latest conversation turn to OpenViking after each response."""
    envelope = ctx.result.envelope
    user_text = envelope.body
    assistant_text = ctx.result.response_text
    session_id = _session_key(envelope.room_id, envelope.target.resolved_thread_id)
    client = get_client()

    await client.add_message(session_id, "user", user_text)
    await client.add_message(session_id, "assistant", assistant_text)

    pending_tokens = _SESSION_PENDING_TOKENS.get(session_id, 0)
    pending_tokens += _estimate_tokens(user_text) + _estimate_tokens(assistant_text)
    _SESSION_PENDING_TOKENS[session_id] = pending_tokens
    if pending_tokens >= COMMIT_TOKEN_THRESHOLD:
        result = await client.commit_session(session_id)
        if result is not None and _SESSION_PENDING_TOKENS.get(session_id) == pending_tokens:
            _SESSION_PENDING_TOKENS.pop(session_id, None)


@hook(
    event="compaction:before",
    name="openviking-pre-compaction",
    priority=10,
    timeout_ms=30000,
)
async def pre_compaction_archive(ctx: CompactionHookContext) -> None:
    """Archive all messages to OpenViking before MindRoom compacts them away."""
    if not ctx.messages:
        return

    session_id = _session_key(ctx.room_id, ctx.thread_id)
    client = get_client()

    for message in ctx.messages:
        role = message.role
        if role in ("user", "assistant"):
            await client.add_message(session_id, role, _extract_text(message))

    # Synchronous commit to ensure nothing is lost before compaction
    result = await client.commit_session(session_id, wait=True)
    if result is not None:
        _SESSION_PENDING_TOKENS.pop(session_id, None)

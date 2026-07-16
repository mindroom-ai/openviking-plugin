"""Tests for OpenViking hook functions."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import AsyncMock, Mock, call, patch

import httpx
import pytest
from agno.models.message import Message
from mindroom.config.main import Config
from mindroom.constants import RuntimePaths
from mindroom.history.types import HistoryScope
from mindroom.hooks import (
    AfterResponseContext,
    CompactionHookContext,
    MessageEnrichContext,
    MessageEnvelope,
    ResponseResult,
    SenderKind,
    SessionHookContext,
    TurnIntent,
    TurnOrigin,
    TurnTrust,
)
from mindroom.hooks.decorators import get_hook_metadata
from mindroom.message_target import MessageTarget

import openviking.hooks as hooks
from openviking.hooks import (
    _ensure_server_running,
    _estimate_tokens,
    _extract_text,
    _format_memories,
    _session_key,
    archive_turn,
    init_session,
    pre_compaction_archive,
    recall_memories,
)


def _base_kwargs(tmp_path: Path, event_name: str) -> dict[str, object]:
    runtime_paths = RuntimePaths(
        config_path=tmp_path / "config.yaml",
        config_dir=tmp_path,
        env_path=tmp_path / ".env",
        storage_root=tmp_path,
        process_env={},
        env_file_values={},
    )
    return {
        "event_name": event_name,
        "plugin_name": "openviking",
        "settings": {},
        "config": Config(),
        "runtime_paths": runtime_paths,
        "logger": Mock(),
        "correlation_id": "corr-1",
    }


def _envelope(body: str, *, room_id: str = "r1", thread_id: str | None = "t1") -> MessageEnvelope:
    target = MessageTarget(
        room_id=room_id,
        source_thread_id=thread_id,
        resolved_thread_id=thread_id,
        reply_to_event_id=None,
        session_id="mindroom-session-1",
    )
    origin = TurnOrigin(
        transport_sender_id="@user:localhost",
        requester_id="@user:localhost",
        sender_entity_name=None,
        requester_entity_name=None,
        sender_kind=SenderKind.USER,
        requester_kind=SenderKind.USER,
        intent=TurnIntent.USER_MESSAGE,
        source_kind="matrix",
        trust=TurnTrust.EXTERNAL,
    )
    return MessageEnvelope(
        source_event_id="$event",
        target=target,
        body=body,
        attachment_ids=(),
        mentioned_agents=("code",),
        agent_name="code",
        origin=origin,
    )


def _enrich_context(tmp_path: Path, body: str) -> MessageEnrichContext:
    return MessageEnrichContext(
        **_base_kwargs(tmp_path, "message:enrich"),
        envelope=_envelope(body),
        target_entity_name="code",
        target_member_names=None,
    )


def _after_response_context(
    tmp_path: Path,
    *,
    body: str = "hi",
    response_text: str = "hello",
) -> AfterResponseContext:
    return AfterResponseContext(
        **_base_kwargs(tmp_path, "message:after_response"),
        result=ResponseResult(
            response_text=response_text,
            response_event_id="$response",
            delivery_kind="sent",
            response_kind="ai",
            envelope=_envelope(body),
        ),
    )


def _compaction_context(tmp_path: Path, messages: list[Message]) -> CompactionHookContext:
    return CompactionHookContext(
        **_base_kwargs(tmp_path, "compaction:before"),
        agent_name="code",
        scope=HistoryScope(kind="agent", scope_id="code"),
        room_id="r1",
        thread_id="t1",
        messages=messages,
        session_id="mindroom-session-1",
        token_count_before=100,
        token_count_after=None,
        compaction_summary=None,
    )


class TestHookMetadata:
    def test_recall_memories_metadata(self) -> None:
        metadata = get_hook_metadata(recall_memories)
        assert metadata is not None
        assert metadata.event_name == "message:enrich"
        assert metadata.hook_name == "openviking-recall"
        assert metadata.priority == 30

    def test_archive_turn_metadata(self) -> None:
        metadata = get_hook_metadata(archive_turn)
        assert metadata is not None
        assert metadata.event_name == "message:after_response"
        assert metadata.hook_name == "openviking-archive-turn"
        assert metadata.priority == 50

    def test_pre_compaction_metadata(self) -> None:
        metadata = get_hook_metadata(pre_compaction_archive)
        assert metadata is not None
        assert metadata.event_name == "compaction:before"
        assert metadata.hook_name == "openviking-pre-compaction"
        assert metadata.priority == 10

    def test_init_session_metadata(self) -> None:
        metadata = get_hook_metadata(init_session)
        assert metadata is not None
        assert metadata.event_name == "session:started"
        assert metadata.hook_name == "openviking-init-session"
        assert metadata.priority == 10


class TestHelpers:
    def test_estimate_tokens(self) -> None:
        assert _estimate_tokens("abcdefgh") == 2
        assert _estimate_tokens("") == 0

    def test_extract_text_from_agno_message(self) -> None:
        assert _extract_text(Message(role="user", content="hello")) == "hello"
        assert (
            _extract_text(
                Message(
                    role="user",
                    content=[
                        {"type": "text", "text": "a"},
                        {"type": "text", "text": "b"},
                    ],
                )
            )
            == "a\nb"
        )

    def test_format_memories_empty(self) -> None:
        assert _format_memories([], 2000) == ""

    def test_format_memories_with_uri(self) -> None:
        result = _format_memories([{"uri": "viking://u/1", "content": "fact A"}], 2000)
        assert "viking://u/1" in result
        assert "fact A" in result

    def test_format_memories_respects_budget(self) -> None:
        memories = [{"content": "x" * 1000} for _ in range(20)]
        result = _format_memories(memories, 100)
        assert result.count("\n") < 19

    def test_session_key(self) -> None:
        assert _session_key("room1", "thread1") == "room1:thread1"
        assert _session_key("room1", None) == "room1:default"


class TestRecallMemories:
    @pytest.mark.asyncio
    async def test_returns_empty_when_envelope_body_is_blank(self, tmp_path: Path) -> None:
        result = await recall_memories(_enrich_context(tmp_path, "  "))
        assert result == []

    @pytest.mark.asyncio
    async def test_queries_with_current_envelope_body(self, tmp_path: Path) -> None:
        mock_client = AsyncMock()
        mock_client.find.return_value = [{"uri": "viking://u/1", "content": "X is great"}]
        with patch("openviking.hooks.get_client", return_value=mock_client):
            result = await recall_memories(_enrich_context(tmp_path, " tell me about X "))

        mock_client.find.assert_awaited_once_with("tell me about X", namespaces=["user", "agent"], limit=10)
        assert len(result) == 1
        assert result[0].key == "openviking_memories"
        assert result[0].cache_policy == "volatile"
        assert "X is great" in result[0].text

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_memories(self, tmp_path: Path) -> None:
        mock_client = AsyncMock()
        mock_client.find.return_value = []
        with patch("openviking.hooks.get_client", return_value=mock_client):
            result = await recall_memories(_enrich_context(tmp_path, "hello"))
        assert result == []


class TestArchiveTurn:
    @pytest.mark.asyncio
    async def test_archives_real_response_result(self, tmp_path: Path) -> None:
        mock_client = AsyncMock()
        with (
            patch("openviking.hooks.get_client", return_value=mock_client),
            patch.object(hooks, "_SESSION_PENDING_TOKENS", {}),
        ):
            await archive_turn(_after_response_context(tmp_path))

        assert mock_client.add_message.await_args_list == [
            call("r1:t1", "user", "hi"),
            call("r1:t1", "assistant", "hello"),
        ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("body", "response_text", "expected_calls"),
        [
            ("", "", []),
            ("", "hello", [call("r1:t1", "assistant", "hello")]),
            ("hi", "", [call("r1:t1", "user", "hi")]),
        ],
    )
    async def test_skips_empty_turn_parts(
        self,
        tmp_path: Path,
        body: str,
        response_text: str,
        expected_calls: list[object],
    ) -> None:
        mock_client = AsyncMock()
        pending: dict[str, int] = {}
        with (
            patch("openviking.hooks.get_client", return_value=mock_client),
            patch.object(hooks, "_SESSION_PENDING_TOKENS", pending),
        ):
            await archive_turn(_after_response_context(tmp_path, body=body, response_text=response_text))

        assert mock_client.add_message.await_args_list == expected_calls
        mock_client.commit_session.assert_not_awaited()
        if not expected_calls:
            assert pending == {}

    @pytest.mark.asyncio
    async def test_commits_after_accumulated_token_threshold(self, tmp_path: Path) -> None:
        mock_client = AsyncMock()
        mock_client.commit_session.return_value = {"ok": True}
        pending: dict[str, int] = {}
        with (
            patch("openviking.hooks.get_client", return_value=mock_client),
            patch.object(hooks, "COMMIT_TOKEN_THRESHOLD", 2),
            patch.object(hooks, "_SESSION_PENDING_TOKENS", pending),
        ):
            await archive_turn(_after_response_context(tmp_path, body="abcd", response_text="efgh"))

        mock_client.commit_session.assert_awaited_once_with("r1:t1")
        assert pending == {}


class TestPreCompactionArchive:
    @pytest.mark.asyncio
    async def test_archives_agno_messages_and_commits(self, tmp_path: Path) -> None:
        context = _compaction_context(
            tmp_path,
            [
                Message(role="user", content="msg1"),
                Message(role="assistant", content="msg2"),
                Message(role="system", content="skip me"),
            ],
        )
        mock_client = AsyncMock()
        mock_client.commit_session.return_value = {"ok": True}
        pending = {"r1:t1": 10}
        with (
            patch("openviking.hooks.get_client", return_value=mock_client),
            patch.object(hooks, "_SESSION_PENDING_TOKENS", pending),
        ):
            await pre_compaction_archive(context)

        assert mock_client.add_message.await_args_list == [
            call("r1:t1", "user", "msg1"),
            call("r1:t1", "assistant", "msg2"),
        ]
        mock_client.commit_session.assert_awaited_once_with("r1:t1", wait=True)
        assert pending == {}


class TestInitSession:
    @pytest.mark.asyncio
    async def test_creates_session_from_real_context(self, tmp_path: Path) -> None:
        context = SessionHookContext(
            **_base_kwargs(tmp_path, "session:started"),
            agent_name="code",
            scope=HistoryScope(kind="agent", scope_id="code"),
            session_id="mindroom-session-1",
            room_id="r1",
            thread_id="t1",
        )
        mock_client = AsyncMock()
        mock_client.create_session.return_value = {"session_id": "r1:t1"}
        with (
            patch("openviking.hooks._ensure_server_running", new=AsyncMock()) as ensure_server,
            patch("openviking.hooks.get_client", return_value=mock_client),
        ):
            await init_session(context)

        ensure_server.assert_awaited_once()
        mock_client.create_session.assert_awaited_once_with("r1:t1")


class TestEnsureServerRunning:
    @pytest.mark.asyncio
    async def test_warns_only_once_when_server_is_unreachable(self, caplog: pytest.LogCaptureFixture) -> None:
        mock_http = AsyncMock()
        mock_http.get.side_effect = httpx.ConnectError("connection refused")
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_http

        caplog.set_level(logging.WARNING)
        with (
            patch.object(hooks, "_AUTO_START_ATTEMPTED", False),
            patch("openviking.hooks.httpx.AsyncClient", return_value=mock_client),
        ):
            await _ensure_server_running()
            await _ensure_server_running()

        assert mock_http.get.await_count == 1
        assert "start it manually" in caplog.text

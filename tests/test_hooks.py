"""Tests for OpenViking hook functions."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

import openviking.hooks as hooks
from openviking.hooks import (
    _estimate_tokens,
    _ensure_server_running,
    _extract_last_user_text,
    _extract_text,
    _format_memories,
    _session_key,
    archive_turn,
    init_session,
    pre_compaction_archive,
    recall_memories,
)


# ------------------------------------------------------------------
# Hook metadata
# ------------------------------------------------------------------


class TestHookMetadata:
    def test_recall_memories_metadata(self) -> None:
        assert recall_memories._hook_event == "message:enrich"
        assert recall_memories._hook_name == "openviking-recall"
        assert recall_memories._hook_priority == 30

    def test_archive_turn_metadata(self) -> None:
        assert archive_turn._hook_event == "message:after_response"
        assert archive_turn._hook_name == "openviking-archive-turn"
        assert archive_turn._hook_priority == 50

    def test_pre_compaction_metadata(self) -> None:
        assert pre_compaction_archive._hook_event == "compaction:before"
        assert pre_compaction_archive._hook_name == "openviking-pre-compaction"
        assert pre_compaction_archive._hook_priority == 10

    def test_init_session_metadata(self) -> None:
        assert init_session._hook_event == "session:started"
        assert init_session._hook_name == "openviking-init-session"
        assert init_session._hook_priority == 10


# ------------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------------


class TestHelpers:
    def test_estimate_tokens(self) -> None:
        assert _estimate_tokens("abcdefgh") == 2
        assert _estimate_tokens("") == 0

    def test_extract_last_user_text_string_content(self) -> None:
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        assert _extract_last_user_text(messages) == "hello"

    def test_extract_last_user_text_list_content(self) -> None:
        messages = [
            {"role": "user", "content": [{"type": "text", "text": "from list"}]},
        ]
        assert _extract_last_user_text(messages) == "from list"

    def test_extract_last_user_text_empty(self) -> None:
        assert _extract_last_user_text([]) is None
        assert _extract_last_user_text([{"role": "assistant", "content": "hi"}]) is None

    def test_extract_text_string(self) -> None:
        assert _extract_text({"content": "hello"}) == "hello"

    def test_extract_text_list(self) -> None:
        msg = {"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}
        assert _extract_text(msg) == "a\nb"

    def test_format_memories_empty(self) -> None:
        assert _format_memories([], 2000) == ""

    def test_format_memories_with_uri(self) -> None:
        mems = [{"uri": "viking://u/1", "content": "fact A"}]
        result = _format_memories(mems, 2000)
        assert "viking://u/1" in result
        assert "fact A" in result

    def test_format_memories_respects_budget(self) -> None:
        mems = [{"content": "x" * 1000} for _ in range(20)]
        result = _format_memories(mems, 100)
        # Should have cut off well before 20 entries
        assert result.count("\n") < 19

    def test_session_key(self) -> None:
        ctx = SimpleNamespace(room_id="room1", thread_id="thread1")
        assert _session_key(ctx) == "room1:thread1"

    def test_session_key_defaults(self) -> None:
        ctx = SimpleNamespace()
        assert _session_key(ctx) == "global:default"


# ------------------------------------------------------------------
# Hook functions
# ------------------------------------------------------------------


class TestRecallMemories:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_user_text(self) -> None:
        ctx = SimpleNamespace(messages=[])
        result = await recall_memories(ctx)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_enrichment_items(self) -> None:
        ctx = SimpleNamespace(messages=[{"role": "user", "content": "tell me about X"}])
        mock_client = AsyncMock()
        mock_client.find.return_value = [{"uri": "viking://u/1", "content": "X is great"}]
        with patch("openviking.hooks.get_client", return_value=mock_client):
            result = await recall_memories(ctx)
            assert len(result) == 1
            assert result[0].key == "openviking_memories"
            assert result[0].cache_policy == "volatile"
            assert "X is great" in result[0].text

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_memories(self) -> None:
        ctx = SimpleNamespace(messages=[{"role": "user", "content": "hello"}])
        mock_client = AsyncMock()
        mock_client.find.return_value = []
        with patch("openviking.hooks.get_client", return_value=mock_client):
            result = await recall_memories(ctx)
            assert result == []


class TestArchiveTurn:
    @pytest.mark.asyncio
    async def test_archives_user_and_assistant(self) -> None:
        ctx = SimpleNamespace(
            messages=[
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
            ],
            room_id="r1",
            thread_id="t1",
        )
        mock_client = AsyncMock()
        mock_client.add_message.return_value = {"ok": True}
        mock_client.commit_session.return_value = {"ok": True}
        with patch("openviking.hooks.get_client", return_value=mock_client):
            await archive_turn(ctx)
            assert mock_client.add_message.call_count == 2

    @pytest.mark.asyncio
    async def test_does_nothing_with_empty_messages(self) -> None:
        ctx = SimpleNamespace(messages=[], room_id="r1", thread_id="t1")
        mock_client = AsyncMock()
        with patch("openviking.hooks.get_client", return_value=mock_client):
            await archive_turn(ctx)
            mock_client.add_message.assert_not_called()


class TestPreCompactionArchive:
    @pytest.mark.asyncio
    async def test_archives_all_messages_and_commits(self) -> None:
        ctx = SimpleNamespace(
            messages=[
                {"role": "user", "content": "msg1"},
                {"role": "assistant", "content": "msg2"},
                {"role": "user", "content": "msg3"},
            ],
            session_id="s1",
            room_id="r1",
            thread_id="t1",
        )
        mock_client = AsyncMock()
        mock_client.add_message.return_value = {"ok": True}
        mock_client.commit_session.return_value = {"ok": True}
        with patch("openviking.hooks.get_client", return_value=mock_client):
            await pre_compaction_archive(ctx)
            assert mock_client.add_message.call_count == 3
            mock_client.commit_session.assert_called_once_with("s1", wait=True)


class TestInitSession:
    @pytest.mark.asyncio
    async def test_creates_session(self) -> None:
        ctx = SimpleNamespace(room_id="r1", thread_id="t1")
        mock_client = AsyncMock()
        mock_client.create_session.return_value = {"session_id": "r1:t1"}
        with (
            patch("openviking.hooks._ensure_server_running", new=AsyncMock()) as ensure_server,
            patch("openviking.hooks.get_client", return_value=mock_client),
        ):
            await init_session(ctx)
            ensure_server.assert_awaited_once()
            mock_client.create_session.assert_called_once_with("r1:t1")


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

"""Tests for OpenViking agent-facing tools."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from openviking.tools import memory_forget, memory_recall, memory_store


class TestMemoryRecall:
    @pytest.mark.asyncio
    async def test_returns_results(self) -> None:
        mock_client = AsyncMock()
        mock_client.find.return_value = [
            {"uri": "viking://u/1", "content": "fact A"},
            {"uri": "viking://u/2", "content": "fact B"},
        ]
        with patch("openviking.tools.get_client", return_value=mock_client):
            result = json.loads(await memory_recall("test query"))
            assert result["status"] == "ok"
            assert result["action"] == "recall"
            assert len(result["results"]) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_results(self) -> None:
        mock_client = AsyncMock()
        mock_client.find.return_value = []
        with patch("openviking.tools.get_client", return_value=mock_client):
            result = json.loads(await memory_recall("unknown"))
            assert result["status"] == "ok"
            assert result["results"] == []

    @pytest.mark.asyncio
    async def test_handles_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.find.side_effect = Exception("connection error")
        with patch("openviking.tools.get_client", return_value=mock_client):
            result = json.loads(await memory_recall("test"))
            assert result["status"] == "error"


class TestMemoryStore:
    @pytest.mark.asyncio
    async def test_stores_memory(self) -> None:
        mock_client = AsyncMock()
        mock_client.store_memory.return_value = {"uri": "viking://user/memories/general/abc123"}
        with patch("openviking.tools.get_client", return_value=mock_client):
            result = json.loads(await memory_store("important fact"))
            assert result["status"] == "ok"
            assert result["action"] == "store"
            assert "viking://user/memories/general/" in result["uri"]

    @pytest.mark.asyncio
    async def test_stores_with_category(self) -> None:
        mock_client = AsyncMock()
        mock_client.store_memory.return_value = {"uri": "viking://user/memories/work/abc123"}
        with patch("openviking.tools.get_client", return_value=mock_client):
            result = json.loads(await memory_store("work fact", category="work"))
            assert result["status"] == "ok"
            assert "work" in result["uri"]

    @pytest.mark.asyncio
    async def test_rejects_empty_content(self) -> None:
        result = json.loads(await memory_store(""))
        assert result["status"] == "error"
        assert "empty" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_handles_store_failure(self) -> None:
        mock_client = AsyncMock()
        mock_client.store_memory.return_value = None
        with patch("openviking.tools.get_client", return_value=mock_client):
            result = json.loads(await memory_store("content"))
            assert result["status"] == "error"


class TestMemoryForget:
    @pytest.mark.asyncio
    async def test_deletes_matching_memories(self) -> None:
        mock_client = AsyncMock()
        mock_client.find.return_value = [
            {"uri": "viking://u/1", "content": "fact A"},
            {"uri": "viking://u/2", "content": "fact B"},
        ]
        mock_client.delete_memory.return_value = True
        with patch("openviking.tools.get_client", return_value=mock_client):
            result = json.loads(await memory_forget("test"))
            assert result["status"] == "ok"
            assert result["action"] == "forget"
            assert len(result["deleted"]) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_match(self) -> None:
        mock_client = AsyncMock()
        mock_client.find.return_value = []
        with patch("openviking.tools.get_client", return_value=mock_client):
            result = json.loads(await memory_forget("nothing"))
            assert result["status"] == "ok"
            assert result["deleted"] == []

    @pytest.mark.asyncio
    async def test_rejects_empty_query(self) -> None:
        result = json.loads(await memory_forget(""))
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_reports_partial_failures(self) -> None:
        mock_client = AsyncMock()
        mock_client.find.return_value = [
            {"uri": "viking://u/1", "content": "a"},
            {"uri": "viking://u/2", "content": "b"},
        ]
        mock_client.delete_memory.side_effect = [True, False]
        with patch("openviking.tools.get_client", return_value=mock_client):
            result = json.loads(await memory_forget("test"))
            assert len(result["deleted"]) == 1
            assert len(result["failed"]) == 1

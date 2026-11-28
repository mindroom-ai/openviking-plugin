"""Tests for OpenViking agent-facing tools."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest
from mindroom.plugin_api import Toolkit, toolkit_functions
from mindroom.tool_system.registry import builtin_tool_registry
from mindroom.tool_system.toolkits import ToolkitFinishing, ToolOutputFilePolicy, adapt_toolkit
from openviking.tools import OpenVikingMemoryTools, openviking_factory

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def toolkit() -> OpenVikingMemoryTools:
    return OpenVikingMemoryTools()


class TestToolkitSchema:
    def test_registers_single_openviking_tool_and_schema(self, toolkit: OpenVikingMemoryTools, tmp_path: Path) -> None:
        assert openviking_factory() is OpenVikingMemoryTools
        assert isinstance(toolkit, Toolkit)
        assert toolkit.name == "openviking"
        assert toolkit.instructions
        assert list(toolkit.functions) == ["openviking"]
        assert toolkit.offer_background_after is False
        assert toolkit.offer_output_path is False

        toolkit.function_finishing = ToolkitFinishing(output_files=ToolOutputFilePolicy(workspace_root=tmp_path))
        adapted = adapt_toolkit(toolkit)
        assert len(adapted.functions) == 1

        fn = adapted.functions[0]
        assert fn.name == "openviking"
        assert fn.description
        assert fn.offer_background_after is False
        assert fn.offer_output_path is False
        assert fn.parameters["required"] == ["action"]
        assert fn.parameters["properties"]["action"]["enum"] == ["recall", "store", "forget"]
        assert set(fn.parameters["properties"]) == {"action", "query", "content", "category"}
        assert "background_after" not in fn.parameters["properties"]
        assert "mindroom_output_path" not in fn.parameters["properties"]

        schema = json.dumps({"name": fn.name, "description": fn.description, "parameters": fn.parameters})
        assert len(schema) <= 750

    def test_registers_approval_and_migration_metadata(self) -> None:
        metadata = builtin_tool_registry().get("openviking")
        assert metadata is not None
        assert metadata.action_scoped_grants == ("openviking",)
        assert metadata.retired_functions == {
            "memory_recall": "openviking",
            "memory_store": "openviking",
            "memory_forget": "openviking",
        }

    @pytest.mark.asyncio
    async def test_adapted_entrypoint_invokes_openviking(self, toolkit: OpenVikingMemoryTools) -> None:
        mock_client = AsyncMock()
        mock_client.find.return_value = [{"uri": "viking://u/1", "content": "fact A"}]
        entrypoint = toolkit_functions(toolkit)["openviking"]

        with patch("openviking.tools.get_client", return_value=mock_client):
            result = json.loads(await entrypoint(action="recall", query="fact"))

        assert result["status"] == "ok"
        assert result["action"] == "recall"
        assert result["results"] == [{"uri": "viking://u/1", "content": "fact A"}]


class TestValidation:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_action", ["invalid", "", 123, ["recall"], {"a": 1}, None])
    async def test_rejects_invalid_action(self, toolkit: OpenVikingMemoryTools, bad_action: Any) -> None:
        with patch("openviking.tools.get_client") as mock_get_client:
            result = json.loads(await toolkit.openviking(action=bad_action))

        assert result["status"] == "error"
        assert result["tool"] == "openviking"
        assert "action" not in result
        assert "unsupported action" in result["message"].lower()
        if isinstance(bad_action, str) and bad_action:
            assert bad_action not in result["message"]
        mock_get_client.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("action", "kwargs"),
        [
            ("recall", {}),
            ("recall", {"query": ""}),
            ("recall", {"query": "   "}),
            ("recall", {"query": 123}),
            ("forget", {}),
            ("forget", {"query": ""}),
            ("forget", {"query": "   "}),
            ("forget", {"query": ["x"]}),
            ("store", {}),
            ("store", {"content": ""}),
            ("store", {"content": "   "}),
            ("store", {"content": 123}),
            ("store", {"content": "fact", "category": "   "}),
            ("store", {"content": "fact", "category": 123}),
        ],
    )
    async def test_rejects_missing_blank_or_non_string_args(
        self, toolkit: OpenVikingMemoryTools, action: Any, kwargs: dict[str, Any]
    ) -> None:
        with patch("openviking.tools.get_client") as mock_get_client:
            result = json.loads(await toolkit.openviking(action=action, **kwargs))

        assert result["status"] == "error"
        assert result["action"] == action
        assert "non-empty string" in result["message"].lower()
        mock_get_client.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("action", "kwargs", "unexpected"),
        [
            ("recall", {"query": "q", "content": "c"}, "content"),
            ("recall", {"query": "q", "category": "work"}, "category"),
            ("recall", {"query": "q", "content": "c", "category": "work"}, "content"),
            ("forget", {"query": "q", "content": "c"}, "content"),
            ("forget", {"query": "q", "category": "work"}, "category"),
            ("store", {"content": "c", "query": "q"}, "query"),
            ("store", {"content": "c", "query": ""}, "query"),
        ],
    )
    async def test_rejects_cross_action_args(
        self, toolkit: OpenVikingMemoryTools, action: Any, kwargs: dict[str, Any], unexpected: str
    ) -> None:
        with patch("openviking.tools.get_client") as mock_get_client:
            result = json.loads(await toolkit.openviking(action=action, **kwargs))

        assert result["status"] == "error"
        assert result["action"] == action
        assert unexpected in result["message"]
        mock_get_client.assert_not_called()


class TestRecall:
    @pytest.mark.asyncio
    async def test_returns_results(self, toolkit: OpenVikingMemoryTools) -> None:
        mock_client = AsyncMock()
        mock_client.find.return_value = [
            {"uri": "viking://u/1", "content": "fact A"},
            {"uri": "viking://u/2", "content": "fact B"},
        ]
        with patch("openviking.tools.get_client", return_value=mock_client):
            result = json.loads(await toolkit.openviking(action="recall", query=" test query "))

        mock_client.find.assert_awaited_once_with("test query", namespaces=["user", "agent"], limit=10)
        assert result["status"] == "ok"
        assert result["action"] == "recall"
        assert len(result["results"]) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_results(self, toolkit: OpenVikingMemoryTools) -> None:
        mock_client = AsyncMock()
        mock_client.find.return_value = []
        with patch("openviking.tools.get_client", return_value=mock_client):
            result = json.loads(await toolkit.openviking(action="recall", query="unknown"))

        assert result["status"] == "ok"
        assert result["action"] == "recall"
        assert result["results"] == []

    @pytest.mark.asyncio
    async def test_handles_error(self, toolkit: OpenVikingMemoryTools) -> None:
        mock_client = AsyncMock()
        mock_client.find.side_effect = Exception("connection error")
        with patch("openviking.tools.get_client", return_value=mock_client):
            result = json.loads(await toolkit.openviking(action="recall", query="test"))

        assert result["status"] == "error"
        assert result["action"] == "recall"


class TestStore:
    @pytest.mark.asyncio
    async def test_stores_memory_with_default_category(self, toolkit: OpenVikingMemoryTools) -> None:
        mock_client = AsyncMock()
        mock_client.store_memory.return_value = {
            "session_id": "memory-abc123",
            "archive_uri": "viking://archive/general/abc123",
        }
        with patch("openviking.tools.get_client", return_value=mock_client):
            result = json.loads(await toolkit.openviking(action="store", content=" important fact "))

        uri_arg, content_arg = mock_client.store_memory.await_args.args
        assert uri_arg.startswith("viking://user/memories/general/")
        assert content_arg == "important fact"
        assert result["status"] == "ok"
        assert result["action"] == "store"
        assert result["session_id"] == "memory-abc123"
        assert result["uri"] == "viking://archive/general/abc123"

    @pytest.mark.asyncio
    async def test_stores_with_category(self, toolkit: OpenVikingMemoryTools) -> None:
        mock_client = AsyncMock()
        mock_client.store_memory.return_value = {
            "session_id": "memory-work123",
            "archive_uri": "viking://archive/work/abc123",
        }
        with patch("openviking.tools.get_client", return_value=mock_client):
            result = json.loads(await toolkit.openviking(action="store", content="work fact", category="work"))

        uri_arg, content_arg = mock_client.store_memory.await_args.args
        assert uri_arg.startswith("viking://user/memories/work/")
        assert content_arg == "work fact"
        assert result["status"] == "ok"
        assert result["action"] == "store"
        assert result["session_id"] == "memory-work123"
        assert "work" in result["uri"]

    @pytest.mark.asyncio
    async def test_handles_store_failure(self, toolkit: OpenVikingMemoryTools) -> None:
        mock_client = AsyncMock()
        mock_client.store_memory.return_value = None
        with patch("openviking.tools.get_client", return_value=mock_client):
            result = json.loads(await toolkit.openviking(action="store", content="content"))

        assert result["status"] == "error"
        assert result["action"] == "store"

    @pytest.mark.asyncio
    async def test_handles_store_exception(self, toolkit: OpenVikingMemoryTools) -> None:
        mock_client = AsyncMock()
        mock_client.store_memory.side_effect = Exception("boom")
        with patch("openviking.tools.get_client", return_value=mock_client):
            result = json.loads(await toolkit.openviking(action="store", content="content"))

        assert result["status"] == "error"
        assert result["action"] == "store"


class TestForget:
    @pytest.mark.asyncio
    async def test_deletes_matching_memories(self, toolkit: OpenVikingMemoryTools) -> None:
        mock_client = AsyncMock()
        mock_client.find.return_value = [
            {"uri": "viking://u/1", "content": "fact A"},
            {"uri": "viking://u/2", "content": "fact B"},
        ]
        mock_client.delete_memory.return_value = True
        with patch("openviking.tools.get_client", return_value=mock_client):
            result = json.loads(await toolkit.openviking(action="forget", query="test"))

        assert result["status"] == "ok"
        assert result["action"] == "forget"
        assert result["deleted"] == ["viking://u/1", "viking://u/2"]
        assert result["failed"] == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_match(self, toolkit: OpenVikingMemoryTools) -> None:
        mock_client = AsyncMock()
        mock_client.find.return_value = []
        with patch("openviking.tools.get_client", return_value=mock_client):
            result = json.loads(await toolkit.openviking(action="forget", query="nothing"))

        assert result["status"] == "ok"
        assert result["action"] == "forget"
        assert result["deleted"] == []

    @pytest.mark.asyncio
    async def test_reports_partial_failures(self, toolkit: OpenVikingMemoryTools) -> None:
        mock_client = AsyncMock()
        mock_client.find.return_value = [
            {"uri": "viking://u/1", "content": "a"},
            {"uri": "viking://u/2", "content": "b"},
        ]
        mock_client.delete_memory.side_effect = [True, False]
        with patch("openviking.tools.get_client", return_value=mock_client):
            result = json.loads(await toolkit.openviking(action="forget", query="test"))

        assert result["status"] == "ok"
        assert result["action"] == "forget"
        assert result["deleted"] == ["viking://u/1"]
        assert result["failed"] == ["viking://u/2"]

    @pytest.mark.asyncio
    async def test_handles_search_error(self, toolkit: OpenVikingMemoryTools) -> None:
        mock_client = AsyncMock()
        mock_client.find.side_effect = Exception("connection error")
        with patch("openviking.tools.get_client", return_value=mock_client):
            result = json.loads(await toolkit.openviking(action="forget", query="test"))

        assert result["status"] == "error"
        assert result["action"] == "forget"

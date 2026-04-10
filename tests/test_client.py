"""Tests for the OpenViking HTTP client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviking.client import OpenVikingClient, get_client


@pytest.fixture
def client() -> OpenVikingClient:
    return OpenVikingClient(base_url="http://test:1933")


class TestHealth:
    @pytest.mark.asyncio
    async def test_health_ok(self, client: OpenVikingClient) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            assert await client.health() is True

    @pytest.mark.asyncio
    async def test_health_down(self, client: OpenVikingClient) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            assert await client.health() is False

    @pytest.mark.asyncio
    async def test_health_connection_error(self, client: OpenVikingClient) -> None:
        import httpx

        with patch.object(
            client._http,
            "get",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("refused"),
        ):
            assert await client.health() is False


class TestFind:
    @pytest.mark.asyncio
    async def test_find_returns_results(self, client: OpenVikingClient) -> None:
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.json.return_value = {
            "results": [{"uri": "viking://u/1", "content": "hello"}],
        }
        mock_resp.raise_for_status = MagicMock()
        with patch.object(client._http, "post", new_callable=AsyncMock, return_value=mock_resp):
            results = await client.find("hello")
            assert len(results) == 1
            assert results[0]["uri"] == "viking://u/1"

    @pytest.mark.asyncio
    async def test_find_connection_error(self, client: OpenVikingClient) -> None:
        import httpx

        with patch.object(
            client._http,
            "post",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("refused"),
        ):
            results = await client.find("hello")
            assert results == []


class TestSession:
    @pytest.mark.asyncio
    async def test_create_session(self, client: OpenVikingClient) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"session_id": "test:default"}
        mock_resp.raise_for_status = MagicMock()
        with patch.object(client._http, "post", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.create_session("test:default")
            assert result is not None
            assert result["session_id"] == "test:default"

    @pytest.mark.asyncio
    async def test_add_message(self, client: OpenVikingClient) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True}
        mock_resp.raise_for_status = MagicMock()
        with patch.object(client._http, "post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
            await client.add_message("s1", "user", "hi")
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args
            assert call_kwargs[1]["json"]["role"] == "user"

    @pytest.mark.asyncio
    async def test_commit_session_with_wait(self, client: OpenVikingClient) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"committed": True}
        mock_resp.raise_for_status = MagicMock()
        with patch.object(client._http, "post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
            await client.commit_session("s1", wait=True)
            call_args = mock_post.call_args[0]
            assert "wait=true" in call_args[0]


class TestMemoryOps:
    @pytest.mark.asyncio
    async def test_store_memory(self, client: OpenVikingClient) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"uri": "viking://user/memories/test/abc"}
        mock_resp.raise_for_status = MagicMock()
        with patch.object(client._http, "post", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.store_memory("viking://user/memories/test/abc", "content")
            assert result is not None

    @pytest.mark.asyncio
    async def test_delete_memory_success(self, client: OpenVikingClient) -> None:
        mock_resp = MagicMock()
        mock_resp.is_success = True
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_resp):
            assert await client.delete_memory("viking://user/memories/test/abc") is True

    @pytest.mark.asyncio
    async def test_delete_memory_failure(self, client: OpenVikingClient) -> None:
        mock_resp = MagicMock()
        mock_resp.is_success = False
        with patch.object(client._http, "request", new_callable=AsyncMock, return_value=mock_resp):
            assert await client.delete_memory("viking://user/memories/test/abc") is False

    @pytest.mark.asyncio
    async def test_ls(self, client: OpenVikingClient) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"entries": [{"uri": "viking://u/1"}]}
        mock_resp.raise_for_status = MagicMock()
        with patch.object(client._http, "post", new_callable=AsyncMock, return_value=mock_resp):
            entries = await client.ls("viking://user/memories/")
            assert len(entries) == 1


class TestSingleton:
    def test_get_client_returns_same_instance(self) -> None:
        import openviking.client as mod

        mod._client = None
        c1 = get_client()
        c2 = get_client()
        assert c1 is c2
        mod._client = None

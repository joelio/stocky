"""End-to-end tests against the real FastMCP application.

These drive the server through the SDK's in-memory transport, so tool
registration, JSON schemas and serialisation are all exercised without
spawning a subprocess or touching the network.
"""

from __future__ import annotations

import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from stocky_mcp.config import Config
from stocky_mcp.server import StockyServer, build_server

from .conftest import RecordingTransport

EXPECTED_TOOLS = {"search_stock_images", "get_image_details", "download_image"}


@pytest.fixture
def server(both_providers_transport: RecordingTransport) -> StockyServer:
    """A server whose providers are wired to canned responses.

    Built per test rather than at module scope, so tool registries are not
    shared between tests.
    """
    config = Config(pexels_api_key="pk", unsplash_access_key="uk", cache_ttl=0)
    return build_server(config, transport=both_providers_transport)


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------


async def test_all_tools_are_registered(server: StockyServer) -> None:
    async with create_connected_server_and_client_session(
        server.mcp, raise_exceptions=True
    ) as client:
        tools = await client.list_tools()

    assert {tool.name for tool in tools.tools} == EXPECTED_TOOLS


async def test_tools_have_descriptions(server: StockyServer) -> None:
    async with create_connected_server_and_client_session(
        server.mcp, raise_exceptions=True
    ) as client:
        tools = await client.list_tools()

    assert all(tool.description for tool in tools.tools)


async def test_search_tool_exposes_its_parameters(server: StockyServer) -> None:
    async with create_connected_server_and_client_session(
        server.mcp, raise_exceptions=True
    ) as client:
        tools = await client.list_tools()

    search = next(t for t in tools.tools if t.name == "search_stock_images")
    properties = search.inputSchema["properties"]
    assert {"query", "providers", "per_page", "page", "sort"} <= set(properties)
    assert search.inputSchema["required"] == ["query"]


async def test_help_resource_is_registered(server: StockyServer) -> None:
    async with create_connected_server_and_client_session(
        server.mcp, raise_exceptions=True
    ) as client:
        resources = await client.list_resources()

    assert [str(r.uri) for r in resources.resources] == ["stock-images://help"]


async def test_help_resource_is_markdown(server: StockyServer) -> None:
    """The old code left the default text/plain, so clients rendered it raw."""
    async with create_connected_server_and_client_session(
        server.mcp, raise_exceptions=True
    ) as client:
        result = await client.read_resource("stock-images://help")

    assert result.contents[0].mimeType == "text/markdown"
    assert "Stocky" in result.contents[0].text


# --------------------------------------------------------------------------
# Tool invocation
# --------------------------------------------------------------------------


async def test_search_returns_structured_content(server: StockyServer) -> None:
    async with create_connected_server_and_client_session(
        server.mcp, raise_exceptions=True
    ) as client:
        result = await client.call_tool("search_stock_images", {"query": "trees"})

    assert result.isError is False
    # A dict return annotation is the one case FastMCP does not wrap in
    # {"result": ...}, so callers see these keys directly.
    assert result.structuredContent["query"] == "trees"
    assert set(result.structuredContent["results"]) == {"pexels", "unsplash"}


async def test_search_content_is_valid_json(server: StockyServer) -> None:
    async with create_connected_server_and_client_session(
        server.mcp, raise_exceptions=True
    ) as client:
        result = await client.call_tool("search_stock_images", {"query": "trees"})

    payload = json.loads(result.content[0].text)
    assert payload["total_results"] == 2


async def test_search_honours_a_provider_subset(server: StockyServer) -> None:
    async with create_connected_server_and_client_session(
        server.mcp, raise_exceptions=True
    ) as client:
        result = await client.call_tool(
            "search_stock_images", {"query": "trees", "providers": ["pexels"]}
        )

    assert set(result.structuredContent["results"]) == {"pexels"}


async def test_get_image_details_returns_metadata(server: StockyServer) -> None:
    async with create_connected_server_and_client_session(
        server.mcp, raise_exceptions=True
    ) as client:
        result = await client.call_tool("get_image_details", {"image_id": "pexels_67762"})

    assert result.structuredContent["id"] == "pexels_67762"


async def test_tool_errors_are_returned_as_data_not_failures(
    server: StockyServer,
) -> None:
    """A bad id should be a readable message, not a protocol-level error."""
    async with create_connected_server_and_client_session(
        server.mcp, raise_exceptions=True
    ) as client:
        result = await client.call_tool("get_image_details", {"image_id": "nope"})

    assert result.isError is False
    assert "Malformed image id" in result.structuredContent["error"]


async def test_unknown_tool_is_an_error(server: StockyServer) -> None:
    async with create_connected_server_and_client_session(server.mcp) as client:
        result = await client.call_tool("no_such_tool", {})

    assert result.isError is True


async def test_download_rejects_an_invalid_size(server: StockyServer) -> None:
    async with create_connected_server_and_client_session(
        server.mcp, raise_exceptions=True
    ) as client:
        result = await client.call_tool(
            "download_image", {"image_id": "pexels_67762", "size": "huge"}
        )

    assert "Invalid size" in result.structuredContent["error"]


# --------------------------------------------------------------------------
# Configuration behaviour
# --------------------------------------------------------------------------


async def test_server_starts_without_any_credentials() -> None:
    """Missing keys must not stop the handshake; clients only see a timeout."""
    instance = build_server(Config())

    async with create_connected_server_and_client_session(
        instance.mcp, raise_exceptions=True
    ) as client:
        tools = await client.list_tools()
        result = await client.call_tool("search_stock_images", {"query": "trees"})

    assert {tool.name for tool in tools.tools} == EXPECTED_TOOLS
    assert "No image providers are configured" in result.structuredContent["error"]


def test_run_is_synchronous() -> None:
    """FastMCP.run is sync; the previous 'async def run' awaited a None."""
    import inspect

    assert not inspect.iscoroutinefunction(StockyServer.run)

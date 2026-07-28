"""Integration tests that call the real provider APIs.

These replace the old root-level ``test_stocky.py`` and ``test_mcp_client.py``
scripts, which printed results and could not fail a build.

They are skipped unless real credentials are present, and are excluded from
the default run:

    pytest -m integration            # run only these
    pytest -m "not integration"      # skip them (what CI does)
"""

from __future__ import annotations

import json
import os
from urllib.parse import urlparse

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from stocky_mcp.config import Config
from stocky_mcp.providers.pexels import PexelsProvider
from stocky_mcp.providers.unsplash import UnsplashProvider
from stocky_mcp.server import build_server

pytestmark = pytest.mark.integration

PEXELS_KEY = os.getenv("PEXELS_API_KEY")
UNSPLASH_KEY = os.getenv("UNSPLASH_ACCESS_KEY")

needs_pexels = pytest.mark.skipif(not PEXELS_KEY, reason="PEXELS_API_KEY is not set")
needs_unsplash = pytest.mark.skipif(
    not UNSPLASH_KEY, reason="UNSPLASH_ACCESS_KEY is not set"
)
needs_both = pytest.mark.skipif(
    not (PEXELS_KEY and UNSPLASH_KEY), reason="both provider keys are required"
)


@needs_pexels
async def test_pexels_search_returns_live_results() -> None:
    async with PexelsProvider(PEXELS_KEY or "") as provider:
        results = await provider.search("mountain landscape", per_page=3)

    assert results, "Pexels returned no results for a common query"
    assert len(results) <= 3
    for result in results:
        assert result.id.startswith("pexels_")
        assert result.url.startswith("http")
        assert result.photographer
        assert result.width > 0


@needs_pexels
async def test_pexels_round_trips_search_to_details() -> None:
    async with PexelsProvider(PEXELS_KEY or "") as provider:
        found = await provider.search("ocean", per_page=1)
        details = await provider.get_details(found[0].id)

    assert details is not None
    assert details.id == found[0].id


@needs_unsplash
async def test_unsplash_search_returns_live_results() -> None:
    async with UnsplashProvider(UNSPLASH_KEY or "") as provider:
        results = await provider.search("forest", per_page=3)

    assert results, "Unsplash returned no results for a common query"
    for result in results:
        assert result.id.startswith("unsplash_")
        # Unsplash requires hotlinking its URLs rather than re-hosting.
        # Check the parsed host: a substring match would also accept
        # something like https://evil.example/images.unsplash.com/x.
        assert urlparse(result.url).netloc == "images.unsplash.com"


@needs_unsplash
async def test_unsplash_respects_the_per_page_ceiling() -> None:
    """Above 30 Unsplash falls back to 10, so clamping must really happen."""
    async with UnsplashProvider(UNSPLASH_KEY or "") as provider:
        results = await provider.search("nature", per_page=50)

    assert len(results) == 30


@needs_both
async def test_server_search_tool_against_live_apis() -> None:
    """The old test_mcp_client.py script, as a real assertion."""
    server = build_server(Config.from_env())

    async with create_connected_server_and_client_session(
        server.mcp, raise_exceptions=True
    ) as client:
        tools = await client.list_tools()
        result = await client.call_tool(
            "search_stock_images", {"query": "mountain landscape", "per_page": 2}
        )

    assert {tool.name for tool in tools.tools} == {
        "search_stock_images",
        "get_image_details",
        "download_image",
    }
    payload = json.loads(result.content[0].text)
    assert payload["total_results"] > 0, payload.get("errors")


@needs_both
async def test_help_resource_reads_over_the_protocol() -> None:
    server = build_server(Config.from_env())

    async with create_connected_server_and_client_session(
        server.mcp, raise_exceptions=True
    ) as client:
        result = await client.read_resource("stock-images://help")

    assert "Stocky" in result.contents[0].text


@needs_pexels
async def test_download_writes_a_real_image(tmp_path: object) -> None:
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    server = build_server(Config.from_env())

    search = await server.manager.search("sunset", providers=["pexels"], per_page=1)
    image_id = search["results"]["pexels"][0]["id"]
    result = await server.manager.download_image(
        image_id, size="small", output_path=str(tmp_path / "sunset.jpg")
    )

    assert result.get("success") is True, result
    written = Path(result["path"])
    assert written.exists()
    # JPEG magic bytes, so we know we got an image and not an error page.
    assert written.read_bytes()[:2] == b"\xff\xd8"

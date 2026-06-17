#!/usr/bin/env python3
"""
Test client for Stocky MCP server.

Spawns the Stocky server over stdio (the same transport MCP clients such as
Claude Desktop use), performs the MCP handshake, and exercises the tools and
the help resource.

Requires PEXELS_API_KEY and/or UNSPLASH_ACCESS_KEY in the environment for the
search/details tests to return results; without them the server still starts
and the handshake/tool-listing checks run.

Usage:
    PEXELS_API_KEY=... UNSPLASH_ACCESS_KEY=... python test_mcp_client.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_PATH = Path(__file__).resolve().parent / "stocky_mcp.py"


def _tool_payload(result):
    """Extract the JSON payload returned by a tool call.

    FastMCP serializes a tool's return value into the result's text content
    (and, on newer versions, structuredContent). Prefer the structured value
    when present, otherwise parse the first text block.
    """
    structured = getattr(result, "structuredContent", None)
    if structured:
        # FastMCP wraps a plain return value under a single "result" key.
        if isinstance(structured, dict) and set(structured) == {"result"}:
            return structured["result"]
        return structured
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
    return None


async def run_tests(session: ClientSession) -> None:
    # Handshake
    await session.initialize()
    print("Initialized session with Stocky server")

    # Tools
    tools = (await session.list_tools()).tools
    tool_names = [t.name for t in tools]
    print(f"Available tools: {tool_names}")
    assert "search_stock_images" in tool_names, "search_stock_images missing"

    have_keys = bool(
        os.getenv("PEXELS_API_KEY") or os.getenv("UNSPLASH_ACCESS_KEY")
    )
    if not have_keys:
        print(
            "\nNo API keys set - skipping live search/details tests "
            "(handshake and tool listing passed)."
        )
        return

    # search_stock_images
    print("\nSearching for 'mountain landscape'...")
    search = _tool_payload(
        await session.call_tool(
            "search_stock_images", {"query": "mountain landscape", "per_page": 3}
        )
    )
    results = search.get("results", []) if isinstance(search, dict) else []
    print(f"Found {len(results)} images")
    if results:
        first = results[0]
        print(f"  ID:     {first.get('id')}")
        print(f"  Title:  {first.get('title')}")
        print(f"  Source: {first.get('source')}")

    # get_image_details
    if results:
        image_id = results[0]["id"]
        print(f"\nGetting details for image ID: {image_id}")
        details = _tool_payload(
            await session.call_tool(
                "get_image_details", {"image_id": image_id}
            )
        )
        print("Image details:")
        print(json.dumps(details, indent=2)[:500])

    # help resource
    print("\nListing resources...")
    resources = (await session.list_resources()).resources
    print(f"Available resources: {[str(r.uri) for r in resources]}")
    help_result = await session.read_resource("stock-images://help")
    help_text = help_result.contents[0].text
    print(f"Help resource retrieved: {len(help_text)} characters")


async def main() -> int:
    print("Starting Stocky MCP client tests...\n")

    params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER_PATH)],
        env=os.environ.copy(),
    )

    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await run_tests(session)
    except Exception as e:  # noqa: BLE001 - surface any failure as a test failure
        print(f"\nError during tests: {e}")
        return 1

    print("\nAll tests completed!")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

#!/usr/bin/env python3
"""A small demonstration of the Stocky library API.

This talks to the real Pexels and Unsplash APIs, so it needs credentials:

    export PEXELS_API_KEY=...
    export UNSPLASH_ACCESS_KEY=...
    python demo.py

It exercises the library directly rather than going through MCP. To try the
MCP server itself, point a client at ``uvx stocky-mcp``.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from stocky_mcp.attribution import attribution_for
from stocky_mcp.config import Config
from stocky_mcp.manager import StockImageManager
from stocky_mcp.models import ImageResult


def show(result: dict[str, Any], indent: str = "  ") -> None:
    """Print one search result compactly."""
    image = ImageResult(**{k: v for k, v in result.items() if k != "attribution"})
    print(f"{indent}{image.title[:60]}")
    print(f"{indent}  {image.photographer} · {image.width}x{image.height}")
    print(f"{indent}  {image.url}")
    print(f"{indent}  {attribution_for(image)['text']}")


async def demo_search(manager: StockImageManager) -> None:
    """Search both providers concurrently."""
    print("\n=== Searching all configured providers for 'misty forest' ===")
    response = await manager.search("misty forest", per_page=2)

    if "error" in response:
        print(f"  {response['error']}")
        return

    for provider, results in response["results"].items():
        print(f"\n{provider} — {len(results)} result(s)")
        for result in results:
            show(result)

    # Errors are per-provider now, so one failure no longer hides the rest.
    for provider, message in response.get("errors", {}).items():
        print(f"\n{provider} failed: {message}")


async def demo_filters(manager: StockImageManager) -> None:
    """Apply an orientation filter."""
    print("\n=== Filtered search: landscape orientation ===")
    response = await manager.search("mountains", per_page=1, orientation="landscape")

    for provider, results in response.get("results", {}).items():
        for result in results:
            print(f"\n{provider}")
            show(result)


async def demo_details(manager: StockImageManager) -> None:
    """Fetch full metadata for one image."""
    print("\n=== Image details ===")
    response = await manager.search("coffee", per_page=1)
    results = response.get("results", {})
    first = next((items[0] for items in results.values() if items), None)

    if first is None:
        print("  no results to inspect")
        return

    details = await manager.get_image_details(first["id"], include_attribution=True)
    if "error" in details:
        print(f"  {details['error']}")
        return

    print(f"  id: {details['id']}")
    print(f"  sizes available: {', '.join(sorted(details['sizes']))}")
    print(f"  attribution: {details['attribution']['text']}")


async def demo_cache(manager: StockImageManager) -> None:
    """Show the search cache at work."""
    print("\n=== Search cache ===")
    await manager.search("golden retriever", per_page=1)
    await manager.search("golden retriever", per_page=1)

    stats = manager.cache.stats()
    print(
        f"  enabled={stats['enabled']} hits={stats['hits']} "
        f"misses={stats['misses']} entries={stats['entries']}"
    )


async def main() -> int:
    """Run the demonstrations."""
    config = Config.from_env()
    if not config.configured_providers:
        print(
            "No API keys found. Set PEXELS_API_KEY and/or UNSPLASH_ACCESS_KEY.",
            file=sys.stderr,
        )
        return 1

    print(f"Configured providers: {', '.join(config.configured_providers)}")
    manager = StockImageManager(config)

    await demo_search(manager)
    await demo_filters(manager)
    await demo_details(manager)
    await demo_cache(manager)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

"""MCP server wiring.

Tools are annotated ``-> dict[str, Any]`` deliberately. That is the one return
annotation FastMCP does not wrap in ``{"result": ...}``, so clients receive the
response keys directly as structured content.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from .config import Config, configure_logging
from .manager import StockImageManager
from .models import SIZE_NAMES

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - exercised only without the dependency
    # This must go to stderr. stdout carries JSON-RPC frames, and writing
    # anything else there corrupts the stream, which surfaces in clients as a
    # hang on initialize rather than a readable error.
    print(  # noqa: T201
        "Error: the 'mcp' package is not installed. Install it with: "
        "pip install stocky-mcp",
        file=sys.stderr,
    )
    raise SystemExit(1) from None

logger = logging.getLogger(__name__)

HELP_RESOURCE = """# Stocky — Stock Image Search

Search royalty-free images from Pexels and Unsplash.

## Tools

### `search_stock_images`
Search one or both providers.

- `query` (required) — what to search for.
- `providers` — subset of `["pexels", "unsplash"]`. Defaults to all configured.
- `per_page` — results per provider. Clamped per provider: Pexels allows 80,
  Unsplash allows 30.
- `page` — 1-based page number.
- `sort` — `relevant` or `latest`. Unsplash only; Pexels has no sort option.
- `orientation` — `landscape`, `portrait`, or `square`.
- `color` — a colour name, or a hex code on Pexels.
- `include_attribution` — override the `ENABLE_ATTRIBUTION_LINKS` default.

### `get_image_details`
Full metadata for one image. Takes a prefixed id such as `pexels_12345`
or `unsplash_abc123`.

### `download_image`
Save an image to disk, or return it base64-encoded when no path is given.
Sizes: thumbnail, small, medium, large, original.

## Licensing

Both providers require attribution as a condition of API access. Each result
carries an `attribution` block with ready-made text and HTML when attribution
is enabled — use it. Unsplash additionally requires that displayed images are
hotlinked from their returned URLs rather than re-hosted.

## Tips

- Be specific: "misty pine forest at dawn" beats "trees".
- Results are cached briefly, so repeating a search is cheap.
- Different providers suit different subjects; searching both is usually best.
"""


class StockyServer:
    """Owns the FastMCP application and its tool registrations."""

    def __init__(self, config: Config | None = None) -> None:
        """Build the server.

        Args:
            config: Resolved configuration. Defaults to reading the environment.
        """
        self.config = config or Config.from_env()
        self.manager = StockImageManager(self.config)
        self.mcp = FastMCP("stocky")
        self._register_tools()
        self._register_resources()

    def _register_tools(self) -> None:
        """Register the MCP tools."""

        @self.mcp.tool("search_stock_images")
        async def search_stock_images(
            query: str,
            providers: list[str] | None = None,
            per_page: int = 20,
            page: int = 1,
            sort: str = "relevant",
            orientation: str | None = None,
            color: str | None = None,
            include_attribution: bool | None = None,
        ) -> dict[str, Any]:
            """Search royalty-free stock images from Pexels and Unsplash.

            Args:
                query: What to search for, e.g. "misty pine forest".
                providers: Which providers to search. Defaults to all configured.
                per_page: Results per provider (Pexels max 80, Unsplash max 30).
                page: 1-based page number.
                sort: "relevant" or "latest". Applies to Unsplash only.
                orientation: "landscape", "portrait" or "square".
                color: Colour name, or a hex code on Pexels.
                include_attribution: Include attribution details in results.
            """
            return await self.manager.search(
                query=query,
                providers=providers,
                per_page=per_page,
                page=page,
                sort=sort,
                orientation=orientation,
                color=color,
                include_attribution=include_attribution,
            )

        @self.mcp.tool("get_image_details")
        async def get_image_details(
            image_id: str,
            include_attribution: bool | None = None,
        ) -> dict[str, Any]:
            """Get full metadata for a single image.

            Args:
                image_id: Prefixed id, e.g. "pexels_12345" or "unsplash_abc".
                include_attribution: Include attribution details.
            """
            return await self.manager.get_image_details(
                image_id, include_attribution=include_attribution
            )

        @self.mcp.tool("download_image")
        async def download_image(
            image_id: str,
            size: str = "original",
            output_path: str | None = None,
        ) -> dict[str, Any]:
            """Download an image to disk, or return it base64-encoded.

            Args:
                image_id: Prefixed id, e.g. "pexels_12345".
                size: One of thumbnail, small, medium, large, original.
                output_path: Where to save it. Omit to get base64 data back.
            """
            return await self.manager.download_image(
                image_id, size=size, output_path=output_path
            )

    def _register_resources(self) -> None:
        """Register the MCP resources."""

        @self.mcp.resource(
            "stock-images://help",
            name="help",
            title="Stocky usage guide",
            description="How to search, filter and download stock images",
            mime_type="text/markdown",
        )
        def help_resource() -> str:
            """Return the usage guide."""
            return HELP_RESOURCE

    def run(self) -> None:
        """Run the server over stdio.

        ``FastMCP.run`` is synchronous — it calls ``anyio.run`` internally — so
        this must not be a coroutine. The previous ``async def run`` awaited a
        ``None`` return value and could never have worked.
        """
        self.mcp.run()


def build_server(config: Config | None = None) -> StockyServer:
    """Create a configured server. Useful for tests and embedding."""
    return StockyServer(config)


def main() -> None:
    """Console-script entry point."""
    config = Config.from_env()
    configure_logging(config)

    if not config.configured_providers:
        # A warning, not a fatal error: the server still starts and reports
        # the problem through tool responses, which is far easier for a user
        # to diagnose than a process that exits during the handshake.
        logger.warning(
            "No provider API keys found. Set PEXELS_API_KEY and/or "
            "UNSPLASH_ACCESS_KEY. Searches will return a configuration error."
        )

    logger.info(
        "Starting Stocky MCP server (providers: %s)",
        ", ".join(config.configured_providers) or "none",
    )
    build_server(config).run()


if __name__ == "__main__":  # pragma: no cover
    main()

"""Coordinates the configured providers behind one interface."""

from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import Path
from typing import Any

import httpx

from .attribution import attribution_for
from .cache import TTLCache
from .config import Config
from .errors import ProviderError
from .models import SIZE_NAMES, ImageResult
from .providers.base import StockImageProvider
from .providers.pexels import PexelsProvider
from .providers.unsplash import UnsplashProvider

logger = logging.getLogger(__name__)

PROVIDER_CLASSES: dict[str, type[StockImageProvider]] = {
    "pexels": PexelsProvider,
    "unsplash": UnsplashProvider,
}


class StockImageManager:
    """Fans a query out across providers and normalises the responses."""

    def __init__(
        self,
        config: Config | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Build a manager from ``config``.

        Args:
            config: Resolved configuration. Defaults to reading the environment.
            transport: Optional httpx transport shared by every provider.
                Tests pass a ``MockTransport`` so nothing touches the network.
        """
        self.config = config or Config.from_env()
        self._transport = transport
        self.cache = TTLCache(ttl=self.config.cache_ttl)

        self.providers: dict[str, StockImageProvider] = {}
        credentials = {
            "pexels": self.config.pexels_api_key,
            "unsplash": self.config.unsplash_access_key,
        }
        for name, key in credentials.items():
            if not key:
                continue
            self.providers[name] = PROVIDER_CLASSES[name](
                key,
                timeout=self.config.http_timeout,
                user_agent=self.config.user_agent,
                transport=transport,
            )

    @property
    def available_providers(self) -> list[str]:
        """Names of providers that have credentials."""
        return list(self.providers)

    def _no_providers_error(self) -> dict[str, Any]:
        return {
            "error": (
                "No image providers are configured. Set at least one API key: "
                "PEXELS_API_KEY for Pexels, UNSPLASH_ACCESS_KEY for Unsplash."
            ),
            "results": {},
        }

    @staticmethod
    def _cache_key(
        query: str,
        providers: list[str],
        per_page: int,
        page: int,
        sort: str,
        extra: dict[str, Any],
    ) -> str:
        """Build a canonical cache key.

        Provider names and filters are sorted so that logically identical
        searches written in a different order share one entry.
        """
        filters = "&".join(f"{k}={extra[k]}" for k in sorted(extra) if extra[k])
        return "|".join(
            [
                query.strip().lower(),
                ",".join(sorted(providers)),
                str(per_page),
                str(page),
                sort,
                filters,
            ]
        )

    async def search(
        self,
        query: str,
        providers: list[str] | None = None,
        per_page: int = 20,
        page: int = 1,
        sort: str = "relevant",
        include_attribution: bool | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Search every requested provider concurrently.

        A provider that fails does not fail the whole search: its error is
        reported under ``errors`` while the others still return results.

        Returns:
            A dictionary with ``query``, ``page``, ``per_page``, ``providers``,
            ``results`` keyed by provider, ``errors`` and ``total_results``.
        """
        if not self.providers:
            return self._no_providers_error()

        requested = providers if providers is not None else list(self.providers)
        selected = [name for name in requested if name in self.providers]
        if not selected:
            return {
                "error": (
                    f"None of the requested providers are configured: "
                    f"{', '.join(requested)}. Available: "
                    f"{', '.join(self.providers) or 'none'}."
                ),
                "results": {},
            }

        show_attribution = (
            include_attribution
            if include_attribution is not None
            else self.config.enable_attribution
        )

        filters = {
            key: kwargs.get(key) for key in ("orientation", "color", "size", "locale")
        }
        cache_key = self._cache_key(query, selected, per_page, page, sort, filters)

        cached = self.cache.get(cache_key)
        if cached is not None:
            # Attribution is a presentation concern, so it is applied after
            # the cache rather than being baked into the cached payload.
            return self._apply_attribution(cached, show_attribution)

        # gather() rather than a loop: with httpx these genuinely overlap,
        # so two providers cost one provider's latency.
        outcomes = await asyncio.gather(
            *(
                self._search_one(name, query, per_page, page, sort, kwargs)
                for name in selected
            )
        )

        results: dict[str, list[dict[str, Any]]] = {}
        errors: dict[str, str] = {}
        for name, images, error in outcomes:
            results[name] = [image.to_dict() for image in images]
            if error:
                errors[name] = error

        payload: dict[str, Any] = {
            "query": query,
            "page": page,
            "per_page": per_page,
            "providers": selected,
            "results": results,
            "total_results": sum(len(items) for items in results.values()),
        }
        if errors:
            payload["errors"] = errors

        # Only cache a search that fully succeeded; caching a transient auth
        # or rate-limit failure would keep serving it for the whole TTL.
        if not errors:
            self.cache.set(cache_key, payload)

        return self._apply_attribution(payload, show_attribution)

    async def _search_one(
        self,
        name: str,
        query: str,
        per_page: int,
        page: int,
        sort: str,
        kwargs: dict[str, Any],
    ) -> tuple[str, list[ImageResult], str | None]:
        """Search a single provider, converting failures into a message."""
        provider = self.providers[name]
        try:
            async with provider:
                images = await provider.search(
                    query, per_page=per_page, page=page, sort=sort, **kwargs
                )
        except ProviderError as exc:
            logger.warning("%s search failed: %s", name, exc)
            return name, [], str(exc)
        except Exception as exc:  # noqa: BLE001 - one provider must not break the rest
            logger.exception("Unexpected error searching %s", name)
            return name, [], f"Unexpected error from {name}: {exc}"
        return name, images, None

    def _apply_attribution(
        self,
        payload: dict[str, Any],
        show_attribution: bool,
    ) -> dict[str, Any]:
        """Add or strip attribution on a copy of ``payload``.

        The cached payload must not be mutated, or the first caller's
        attribution preference would leak to everyone who shares the entry.
        """
        results = {
            name: [self._with_attribution(item, show_attribution) for item in items]
            for name, items in payload.get("results", {}).items()
        }
        return {**payload, "results": results}

    @staticmethod
    def _with_attribution(item: dict[str, Any], show: bool) -> dict[str, Any]:
        copy = dict(item)
        if not show:
            copy["attribution_url"] = None
            copy.pop("attribution", None)
            return copy
        copy["attribution"] = attribution_for(ImageResult(**item))
        return copy

    async def get_image_details(
        self,
        image_id: str,
        include_attribution: bool | None = None,
    ) -> dict[str, Any]:
        """Fetch full metadata for one prefixed image id, e.g. ``pexels_123``."""
        provider, error = self._resolve_provider(image_id)
        if error:
            return {"error": error}
        assert provider is not None  # narrowed by _resolve_provider

        show_attribution = (
            include_attribution
            if include_attribution is not None
            else self.config.enable_attribution
        )

        try:
            async with provider:
                result = await provider.get_details(image_id)
        except ProviderError as exc:
            logger.warning("%s details failed: %s", provider.name, exc)
            return {"error": str(exc)}

        if result is None:
            return {"error": f"Image not found: {image_id}"}

        return self._with_attribution(result.to_dict(), show_attribution)

    def _resolve_provider(
        self,
        image_id: str,
    ) -> tuple[StockImageProvider | None, str | None]:
        """Map a prefixed image id onto a configured provider."""
        if "_" not in image_id:
            return None, (
                f"Malformed image id: {image_id!r}. Expected "
                f"'<provider>_<id>', for example 'pexels_12345'."
            )

        name = image_id.split("_", 1)[0]
        if name not in PROVIDER_CLASSES:
            return None, (
                f"Unknown provider {name!r} in image id {image_id!r}. "
                f"Known providers: {', '.join(PROVIDER_CLASSES)}."
            )
        if name not in self.providers:
            return None, (
                f"Provider {name!r} is not configured. Set its API key to "
                f"use it."
            )
        return self.providers[name], None

    def _resolve_output_path(self, output_path: str) -> tuple[Path | None, str | None]:
        """Validate a caller-supplied download path.

        When ``STOCKY_DOWNLOAD_ROOT`` is set, writes are confined to it. This
        matters because the path arrives from a model-generated tool call, so
        ``../../.ssh/authorized_keys`` is a realistic input rather than a
        hypothetical one.
        """
        candidate = Path(output_path).expanduser()
        root = self.config.download_root

        if root is None:
            return candidate, None

        root_path = Path(root).expanduser().resolve()
        if not candidate.is_absolute():
            candidate = root_path / candidate

        try:
            resolved = candidate.resolve()
            resolved.relative_to(root_path)
        except (ValueError, OSError):
            return None, (
                f"Refusing to write outside STOCKY_DOWNLOAD_ROOT ({root_path})."
            )
        return resolved, None

    async def download_image(
        self,
        image_id: str,
        size: str = "original",
        output_path: str | None = None,
    ) -> dict[str, Any]:
        """Download an image to disk, or return it base64-encoded.

        Args:
            image_id: Prefixed image id, e.g. ``unsplash_abc123``.
            size: One of :data:`~stocky_mcp.models.SIZE_NAMES`.
            output_path: Where to save. When omitted the bytes are returned
                base64-encoded instead.

        Returns:
            A dictionary describing the download, or one containing ``error``.
        """
        if size not in SIZE_NAMES:
            return {
                "error": (
                    f"Invalid size {size!r}. Valid options: {', '.join(SIZE_NAMES)}."
                )
            }

        provider, error = self._resolve_provider(image_id)
        if error:
            return {"error": error}
        assert provider is not None

        resolved_path: Path | None = None
        if output_path:
            resolved_path, path_error = self._resolve_output_path(output_path)
            if path_error:
                return {"error": path_error}

        try:
            async with provider:
                result = await provider.get_details(image_id)
                if result is None:
                    return {"error": f"Image not found: {image_id}"}

                image_url = result.url_for_size(size)
                if not image_url:
                    return {
                        "error": f"No URL available for size {size!r} on {image_id}."
                    }

                # Unsplash's licence requires reporting the download. Do it
                # before fetching so a refusal is visible in the logs even if
                # the transfer then fails.
                if isinstance(provider, UnsplashProvider):
                    await self._ping_unsplash(provider, image_id)

                payload = await self._fetch_bytes(provider, image_url)
        except ProviderError as exc:
            return {"error": str(exc)}

        if "error" in payload:
            return payload

        data: bytes = payload["data"]
        content_type: str = payload["content_type"]

        if resolved_path is not None:
            return self._write_to_disk(resolved_path, data, content_type)

        return {
            "success": True,
            "message": "Image data retrieved successfully",
            "data": base64.b64encode(data).decode("ascii"),
            "encoding": "base64",
            "size": len(data),
            "content_type": content_type,
            "attribution": attribution_for(result),
        }

    async def _ping_unsplash(self, provider: UnsplashProvider, image_id: str) -> None:
        """Fire Unsplash's mandatory download counter, ignoring failures."""
        photo_id = provider.strip_prefix(image_id)
        try:
            data = await provider.request_json(f"/photos/{photo_id}")
            location = (data.get("links") or {}).get("download_location")
            if location:
                await provider.trigger_download(location)
        except Exception as exc:  # noqa: BLE001 - compliance ping is best-effort
            logger.warning("Could not report Unsplash download: %s", exc)

    async def _fetch_bytes(
        self,
        provider: StockImageProvider,
        url: str,
    ) -> dict[str, Any]:
        """Stream an image, refusing anything over the configured size cap."""
        limit = self.config.max_download_bytes
        chunks: list[bytes] = []
        total = 0

        try:
            async with provider.client.stream("GET", url) as response:
                if response.status_code != 200:
                    return {
                        "error": (
                            f"Failed to download image: HTTP "
                            f"{response.status_code}"
                        )
                    }

                # Trust the advertised length when present, so an oversized
                # file is rejected before any of it is transferred.
                declared = response.headers.get("Content-Length")
                if declared and declared.isdigit() and int(declared) > limit:
                    return {
                        "error": (
                            f"Image is {int(declared)} bytes, over the "
                            f"{limit} byte limit (STOCKY_MAX_DOWNLOAD_BYTES)."
                        )
                    }

                content_type = response.headers.get("Content-Type", "image/jpeg")

                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    # Re-check while streaming: Content-Length may be absent
                    # or wrong, and this bounds memory either way.
                    if total > limit:
                        return {
                            "error": (
                                f"Download exceeded the {limit} byte limit "
                                f"(STOCKY_MAX_DOWNLOAD_BYTES)."
                            )
                        }
                    chunks.append(chunk)
        except httpx.HTTPError as exc:
            return {"error": f"Failed to download image: {exc}"}

        return {"data": b"".join(chunks), "content_type": content_type}

    @staticmethod
    def _write_to_disk(
        path: Path,
        data: bytes,
        content_type: str,
    ) -> dict[str, Any]:
        """Write ``data`` to ``path``, adding a file extension if needed."""
        extension = content_type.split("/")[-1].split(";")[0].strip().lower()
        if extension not in {"jpeg", "jpg", "png", "gif", "webp", "avif"}:
            extension = "jpg"

        if not path.suffix:
            path = path.with_suffix(f".{extension}")

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        except OSError as exc:
            logger.error("Could not save image to %s: %s", path, exc)
            return {"error": f"Failed to save image: {exc}"}

        return {
            "success": True,
            "message": f"Image downloaded successfully to {path}",
            "path": str(path),
            "size": len(data),
            "content_type": content_type,
        }

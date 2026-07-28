"""Coordinates the configured providers behind one interface."""

from __future__ import annotations

import asyncio
import base64
import copy
import ipaddress
import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

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

#: Extensions an image may be written with. A download path arrives from a
#: model-generated tool call, so refusing anything else stops the tool being
#: used to plant a .plist, .py or .json at an attacker-chosen location.
IMAGE_SUFFIXES = frozenset(
    {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp", ".tiff"}
)

#: Content types that map onto a sensible file extension.
CONTENT_TYPE_SUFFIXES = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/avif": "avif",
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

        # Only credentials are held. Provider *instances* are built per
        # operation, because a provider owns a single HTTP client attribute
        # that its async context manager creates and closes. Sharing one
        # instance across concurrent tool calls meant the first call to finish
        # closed the client out from under the others.
        self._credentials: dict[str, str] = {}
        for name, key in (
            ("pexels", self.config.pexels_api_key),
            ("unsplash", self.config.unsplash_access_key),
        ):
            if key:
                self._credentials[name] = key

    @property
    def available_providers(self) -> list[str]:
        """Names of providers that have credentials."""
        return list(self._credentials)

    def _make_provider(self, name: str) -> StockImageProvider:
        """Build a fresh provider instance, safe to use concurrently."""
        return PROVIDER_CLASSES[name](
            self._credentials[name],
            timeout=self.config.http_timeout,
            user_agent=self.config.user_agent,
            transport=self._transport,
        )

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
        """Build a canonical, unambiguous cache key.

        Every segment is percent-encoded. Without that, caller-supplied text
        containing the separators could forge another search's key: a colour of
        ``red&orientation=landscape`` produced the same key as a genuine
        ``color=red, orientation=landscape`` search.
        """

        def enc(value: Any) -> str:
            return quote(str(value), safe="")

        filters = "&".join(
            f"{enc(k)}={enc(extra[k])}" for k in sorted(extra) if extra[k] is not None
        )
        return "|".join(
            [
                enc(query.strip().lower()),
                ",".join(enc(name) for name in sorted(providers)),
                str(per_page),
                str(page),
                enc(sort),
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
        selected, selection_error = self._select_providers(providers)
        if selection_error is not None:
            return selection_error

        # Normalise before both the cache key and the echoed response, so a
        # cache hit cannot report a different page than the caller asked for.
        per_page = max(1, min(int(per_page), 200))
        page = max(1, int(page))

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

        payload = self._build_payload(query, selected, per_page, page, outcomes)

        # Only cache a search that fully succeeded; caching a transient auth
        # or rate-limit failure would keep serving it for the whole TTL.
        if "errors" not in payload:
            self.cache.set(cache_key, payload)

        return self._apply_attribution(payload, show_attribution)

    def _select_providers(
        self,
        requested: list[str] | None,
    ) -> tuple[list[str], dict[str, Any] | None]:
        """Resolve the provider list, or explain why none are usable."""
        if not self._credentials:
            return [], self._no_providers_error()

        # An empty list means "no preference", same as omitting it. A JSON-RPC
        # client cannot reliably distinguish [] from null, and refusing to
        # search at all is never the useful reading.
        wanted = list(requested) if requested else self.available_providers

        # Deduplicate while preserving order: a repeated name would otherwise
        # issue the same request twice and burn quota for nothing.
        selected: list[str] = []
        for name in wanted:
            if name in self._credentials and name not in selected:
                selected.append(name)

        if not selected:
            return [], {
                "error": (
                    f"None of the requested providers are configured: "
                    f"{', '.join(wanted)}. Available: "
                    f"{', '.join(self.available_providers) or 'none'}."
                ),
                "results": {},
            }
        return selected, None

    @staticmethod
    def _build_payload(
        query: str,
        selected: list[str],
        per_page: int,
        page: int,
        outcomes: list[tuple[str, list[ImageResult], str | None]],
    ) -> dict[str, Any]:
        """Assemble the response from each provider's outcome."""
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
        return payload

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
        try:
            async with self._make_provider(name) as provider:
                images = await provider.search(
                    query, per_page=per_page, page=page, sort=sort, **kwargs
                )
        except ProviderError as exc:
            logger.warning("%s search failed: %s", name, exc)
            return name, [], str(exc)
        # Deliberately broad: one provider must not break the rest.
        except Exception as exc:
            logger.exception("Unexpected error searching %s", name)
            return name, [], f"Unexpected error from {name}: {exc}"
        return name, images, None

    def _apply_attribution(
        self,
        payload: dict[str, Any],
        show_attribution: bool,
    ) -> dict[str, Any]:
        """Add or strip attribution on a deep copy of ``payload``.

        A shallow copy is not enough. The cached payload's nested ``sizes``,
        ``tags`` and provider lists would still be shared, so a caller that
        mutated a returned result would silently corrupt every later cache hit.
        """
        copied = copy.deepcopy(payload)
        copied["results"] = {
            name: [self._with_attribution(item, show_attribution) for item in items]
            for name, items in copied.get("results", {}).items()
        }
        return copied

    @staticmethod
    def _with_attribution(item: dict[str, Any], show: bool) -> dict[str, Any]:
        """Attach or remove the attribution block for one result."""
        copy_of = dict(item)
        # Drop any block from a previous pass: it is not an ImageResult field,
        # so reconstructing the model with it present would raise TypeError.
        copy_of.pop("attribution", None)

        if not show:
            copy_of["attribution_url"] = None
            return copy_of

        copy_of["attribution"] = attribution_for(ImageResult(**copy_of))
        return copy_of

    async def get_image_details(
        self,
        image_id: str,
        include_attribution: bool | None = None,
    ) -> dict[str, Any]:
        """Fetch full metadata for one prefixed image id, e.g. ``pexels_123``."""
        name, error = self._resolve_provider_name(image_id)
        if name is None:
            return {"error": error or f"Could not resolve a provider for {image_id!r}"}

        show_attribution = (
            include_attribution
            if include_attribution is not None
            else self.config.enable_attribution
        )

        try:
            async with self._make_provider(name) as provider:
                result = await provider.get_details(image_id)
        except ProviderError as exc:
            logger.warning("%s details failed: %s", name, exc)
            return {"error": str(exc)}
        # Deliberately broad: an MCP tool must return an error, not raise.
        except Exception as exc:
            # A 200 response with an unexpected shape used to raise KeyError
            # straight out of the tool instead of returning an error.
            logger.exception("Unexpected error fetching details for %s", image_id)
            return {"error": f"Unexpected error from {name}: {exc}"}

        if result is None:
            return {"error": f"Image not found: {image_id}"}

        return self._with_attribution(result.to_dict(), show_attribution)

    def _resolve_provider_name(self, image_id: str) -> tuple[str | None, str | None]:
        """Map a prefixed image id onto a configured provider name."""
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
        if name not in self._credentials:
            return None, (
                f"Provider {name!r} is not configured. Set its API key to use it."
            )
        return name, None

    def _resolve_output_path(self, output_path: str) -> tuple[Path | None, str | None]:
        """Validate a caller-supplied download path.

        The path arrives from a model-generated tool call, so it is treated as
        untrusted: the extension is restricted to image types, and when
        ``STOCKY_DOWNLOAD_ROOT`` is set, writes are confined to it.
        """
        try:
            candidate = Path(output_path).expanduser()
        except (ValueError, OSError, RuntimeError) as exc:
            return None, f"Invalid output path: {exc}"

        # Refuse a non-image extension whether or not a root is configured.
        # Without this the tool can write bytes to ~/Library/LaunchAgents/x.plist
        # or a .py on the import path.
        suffix = candidate.suffix.lower()
        if suffix and suffix not in IMAGE_SUFFIXES:
            return None, (
                f"Refusing to write {suffix!r}. Downloads must use an image "
                f"extension: {', '.join(sorted(IMAGE_SUFFIXES))}."
            )

        root = self.config.download_root
        if root is None:
            try:
                # resolve() also surfaces embedded null bytes as ValueError
                # here rather than deeper in the write.
                return candidate.resolve(), None
            except (ValueError, OSError) as exc:
                return None, f"Invalid output path: {exc}"

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

    @staticmethod
    def _validate_image_url(url: str) -> str | None:
        """Reject image URLs that should never be fetched.

        The URL comes from a provider's JSON body. httpx ignores ``base_url``
        for an absolute URL, so an unchecked value would let a hostile or
        compromised response point the fetch at an internal address.

        Returns:
            An error message, or ``None`` if the URL is acceptable.
        """
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return f"Refusing to fetch a non-HTTP image URL ({parsed.scheme or 'none'})."

        host = parsed.hostname
        if not host:
            return "Refusing to fetch an image URL with no host."

        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return None  # A hostname; DNS resolution is out of scope here.

        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
        ):
            return f"Refusing to fetch an image from a private address ({host})."
        return None

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

        name, error = self._resolve_provider_name(image_id)
        if name is None:
            return {"error": error or f"Could not resolve a provider for {image_id!r}"}

        resolved_path: Path | None = None
        if output_path:
            resolved_path, path_error = self._resolve_output_path(output_path)
            if path_error:
                return {"error": path_error}

        try:
            async with self._make_provider(name) as provider:
                result = await provider.get_details(image_id)
                if result is None:
                    return {"error": f"Image not found: {image_id}"}

                image_url = result.url_for_size(size)
                if not image_url:
                    return {"error": f"No URL available for size {size!r} on {image_id}."}

                url_error = self._validate_image_url(image_url)
                if url_error:
                    return {"error": url_error}

                # Unsplash's licence requires reporting the download. The
                # location travels on the result, so this costs no extra
                # metadata fetch.
                if isinstance(provider, UnsplashProvider) and result.download_location:
                    await provider.trigger_download(result.download_location)

                payload = await self._fetch_bytes(image_url)
        except ProviderError as exc:
            return {"error": str(exc)}
        # Deliberately broad: an MCP tool must return an error, not raise.
        except Exception as exc:
            logger.exception("Unexpected error downloading %s", image_id)
            return {"error": f"Unexpected error downloading {image_id}: {exc}"}

        if "error" in payload:
            return payload

        data: bytes = payload["data"]
        content_type: str = payload["content_type"]

        if resolved_path is not None:
            written = self._write_to_disk(resolved_path, data, content_type)
            if "error" not in written:
                # Saving is exactly the act the licences call "taking" the
                # photo, so attribution must travel with it.
                written["attribution"] = attribution_for(result)
            return written

        return {
            "success": True,
            "message": "Image data retrieved successfully",
            "data": base64.b64encode(data).decode("ascii"),
            "encoding": "base64",
            "size": len(data),
            "content_type": content_type,
            "attribution": attribution_for(result),
        }

    async def _fetch_bytes(self, url: str) -> dict[str, Any]:
        """Stream an image, refusing anything over the configured size cap.

        Uses its own client rather than the provider's. The provider client
        carries the API key on every request, and the image CDN is a different
        origin with no business seeing it.
        """
        limit = self.config.max_download_bytes
        chunks: list[bytes] = []
        total = 0

        client = httpx.AsyncClient(
            timeout=self.config.http_timeout,
            transport=self._transport,
            follow_redirects=True,
            max_redirects=5,
            headers={
                "User-Agent": self.config.user_agent,
                # Images are already compressed, so there is nothing to gain
                # from an encoded response — and accepting one would let a
                # small compressed body decode past the cap before it is seen.
                "Accept-Encoding": "identity",
            },
        )

        try:
            async with client, client.stream("GET", url) as response:
                if response.status_code != 200:
                    return {
                        "error": (
                            f"Failed to download image: HTTP {response.status_code}"
                        )
                    }

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
                    # Re-check while streaming: Content-Length may be
                    # absent or wrong, and this bounds memory either way.
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

        if total == 0:
            return {"error": "The image URL returned an empty response."}

        return {"data": b"".join(chunks), "content_type": content_type}

    @staticmethod
    def _write_to_disk(
        path: Path,
        data: bytes,
        content_type: str,
    ) -> dict[str, Any]:
        """Write ``data`` to ``path``, adding a file extension if needed."""
        if not path.suffix:
            base = content_type.split(";")[0].strip().lower()
            path = path.with_suffix(f".{CONTENT_TYPE_SUFFIXES.get(base, 'jpg')}")

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

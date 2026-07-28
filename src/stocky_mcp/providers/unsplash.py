"""Unsplash provider.

API reference: https://unsplash.com/documentation
Guidelines: https://help.unsplash.com/en/articles/2511245-unsplash-api-guidelines
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..models import ImageResult
from .base import StockImageProvider

logger = logging.getLogger(__name__)

#: Unlike Pexels, Unsplash does NOT clamp an oversized per_page — it silently
#: falls back to its default of 10, so asking for 50 returns fewer images than
#: asking for 30. Clamping client-side is mandatory, not a nicety.
MAX_PER_PAGE = 30

SIZE_MAP = {
    "thumbnail": "thumb",
    "small": "small",
    "medium": "regular",
    "large": "full",
    "original": "raw",
}

VALID_ORDER_BY = frozenset({"relevant", "latest"})
VALID_ORIENTATIONS = frozenset({"landscape", "portrait", "squarish"})
VALID_COLORS = frozenset(
    {
        "black_and_white",
        "black",
        "white",
        "yellow",
        "orange",
        "red",
        "purple",
        "magenta",
        "green",
        "teal",
        "blue",
    }
)

#: Unsplash uses "squarish" where Pexels uses "square".
ORIENTATION_ALIASES = {"square": "squarish"}

LICENSE = "Unsplash License — free to use"


class UnsplashProvider(StockImageProvider):
    """Search and fetch photos from Unsplash."""

    name = "unsplash"
    base_url = "https://api.unsplash.com"

    @classmethod
    def missing_key_message(cls) -> str:
        """Guidance shown when the Unsplash credential is absent."""
        return (
            "Unsplash access key is missing. Set the UNSPLASH_ACCESS_KEY "
            "environment variable. Get a free key at "
            "https://unsplash.com/developers"
        )

    def auth_headers(self) -> dict[str, str]:
        """Unsplash expects a ``Client-ID`` scheme and an API version."""
        return {
            "Authorization": f"Client-ID {self.api_key}",
            "Accept-Version": "v1",
        }

    def is_rate_limited(self, response: httpx.Response) -> bool:
        """Unsplash signals exhaustion with 403, not 429.

        A plain 403 means "forbidden", so the remaining-quota header is what
        distinguishes a rate limit from a rejected key.
        """
        if response.status_code == 429:
            return True
        if response.status_code != 403:
            return False
        return response.headers.get("X-Ratelimit-Remaining") == "0"

    async def search(
        self,
        query: str,
        per_page: int = 20,
        page: int = 1,
        **kwargs: Any,
    ) -> list[ImageResult]:
        """Search Unsplash.

        Args:
            query: Free-text search terms.
            per_page: Results per page, clamped to the API maximum of 30.
            page: 1-based page number.
            **kwargs: Optional ``orientation``, ``color`` and ``sort``
                filters. Unlike Pexels, Unsplash rejects invalid enum values
                with HTTP 400, so they are validated before sending.

        Returns:
            The matching images, or an empty list if there were none.
        """
        params: dict[str, Any] = {
            "query": query,
            "per_page": max(1, min(per_page, MAX_PER_PAGE)),
            "page": max(1, page),
        }

        sort = kwargs.get("sort")
        if sort in VALID_ORDER_BY:
            params["order_by"] = sort

        orientation = kwargs.get("orientation")
        if orientation is not None:
            orientation = ORIENTATION_ALIASES.get(orientation, orientation)
        if orientation in VALID_ORIENTATIONS:
            params["orientation"] = orientation

        color = kwargs.get("color")
        if color in VALID_COLORS:
            params["color"] = color

        data = await self.request_json("/search/photos", params)
        return [self._to_result(photo) for photo in data.get("results", [])]

    async def get_details(self, image_id: str) -> ImageResult | None:
        """Fetch one photo by id."""
        photo_id = self.strip_prefix(image_id)
        data = await self.request_json(f"/photos/{photo_id}")
        return self._to_result(data)

    async def trigger_download(self, download_location: str) -> str | None:
        """Report a download to Unsplash and return the resolved image URL.

        The API guidelines require this whenever a user actually takes a
        photo (saves it, inserts it into a document, and so on). It is a
        counter endpoint, not a way to fetch the image. Failing to call it is
        a licence-compliance violation, so this is invoked on download rather
        than being optional.

        Args:
            download_location: The ``links.download_location`` value from the
                photo, used verbatim — it carries a required ``ixid`` query
                parameter that must not be reconstructed.

        Returns:
            The URL Unsplash resolves to, or ``None`` if the ping failed.
            Failure is logged and swallowed: a broken counter should never
            prevent the caller from getting their image.
        """
        if not download_location:
            return None
        try:
            response = await self.client.get(download_location)
            self._raise_for_status(response)
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 - never block a download
            logger.warning("Unsplash download ping failed: %s", exc)
            return None
        return payload.get("url") if isinstance(payload, dict) else None

    @staticmethod
    def _extract_sizes(urls: dict[str, Any]) -> dict[str, str]:
        """Map Unsplash's ``urls`` onto Stocky's canonical size names."""
        return {
            canonical: urls[unsplash_key]
            for canonical, unsplash_key in SIZE_MAP.items()
            if urls.get(unsplash_key)
        }

    @staticmethod
    def _extract_tags(photo: dict[str, Any]) -> list[str]:
        """Pull tag titles, tolerating the malformed entries the API returns."""
        return [
            tag["title"]
            for tag in photo.get("tags") or []
            if isinstance(tag, dict) and tag.get("title")
        ]

    @staticmethod
    def _extract_text(photo: dict[str, Any], photographer: str) -> tuple[str, str | None]:
        """Resolve a title and description.

        ``description`` is the author's caption and is very often null, while
        ``alt_description`` is generated and almost always present — so the
        fallback order matters for result quality.
        """
        alt = (photo.get("alt_description") or "").strip()
        caption = (photo.get("description") or "").strip()
        title = caption or alt or f"Photo by {photographer}"
        return title, (alt or caption or None)

    def _to_result(self, photo: dict[str, Any]) -> ImageResult:
        """Convert an Unsplash photo object into an :class:`ImageResult`."""
        urls = photo.get("urls") or {}
        user = photo.get("user") or {}
        links = photo.get("links") or {}

        sizes = self._extract_sizes(urls)
        tags = self._extract_tags(photo)
        photographer = user.get("name") or "Unknown"
        title, description = self._extract_text(photo, photographer)

        return ImageResult(
            id=f"{self.name}_{photo['id']}",
            title=title,
            description=description,
            url=urls.get("regular") or urls.get("full") or "",
            thumbnail=urls.get("small") or urls.get("thumb") or "",
            width=photo.get("width", 0),
            height=photo.get("height", 0),
            photographer=photographer,
            photographer_url=(user.get("links") or {}).get("html"),
            source="Unsplash",
            license=LICENSE,
            attribution_url=links.get("html"),
            tags=tags,
            sizes=sizes,
        )

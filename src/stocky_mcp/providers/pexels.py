"""Pexels provider.

API reference: https://www.pexels.com/api/documentation/
"""

from __future__ import annotations

from typing import Any

from ..models import ImageResult
from .base import StockImageProvider

#: Pexels clamps anything above this to 80.
MAX_PER_PAGE = 80

#: Pexels ``src`` keys mapped onto Stocky's canonical size names. Pexels
#: actually returns eight variants; the extras (large2x, portrait, landscape)
#: are kept in ``sizes`` too, since callers occasionally want them.
SIZE_MAP = {
    "thumbnail": "tiny",
    "small": "small",
    "medium": "medium",
    "large": "large",
    "original": "original",
}

EXTRA_SIZES = ("large2x", "portrait", "landscape")

VALID_ORIENTATIONS = frozenset({"landscape", "portrait", "square"})
VALID_SIZES = frozenset({"large", "medium", "small"})

LICENSE = "Pexels License — free to use, attribution appreciated"


class PexelsProvider(StockImageProvider):
    """Search and fetch photos from Pexels."""

    name = "pexels"
    base_url = "https://api.pexels.com/v1"

    @classmethod
    def missing_key_message(cls) -> str:
        """Guidance shown when the Pexels credential is absent."""
        return (
            "Pexels API key is missing. Set the PEXELS_API_KEY environment "
            "variable. Get a free key at https://www.pexels.com/api/"
        )

    def auth_headers(self) -> dict[str, str]:
        """Pexels takes the raw key with no scheme prefix."""
        return {"Authorization": self.api_key}

    async def search(
        self,
        query: str,
        per_page: int = 20,
        page: int = 1,
        **kwargs: Any,
    ) -> list[ImageResult]:
        """Search Pexels.

        Args:
            query: Free-text search terms.
            per_page: Results per page, clamped to the API maximum of 80.
            page: 1-based page number.
            **kwargs: Optional ``orientation``, ``size``, ``color`` and
                ``locale`` filters. Pexels silently ignores invalid filter
                values and still returns 200, so they are validated here
                rather than passed through blindly.

        Returns:
            The matching images, or an empty list if there were none.
        """
        params: dict[str, Any] = {
            "query": query,
            "per_page": max(1, min(per_page, MAX_PER_PAGE)),
            "page": max(1, page),
        }

        orientation = kwargs.get("orientation")
        if orientation in VALID_ORIENTATIONS:
            params["orientation"] = orientation

        size = kwargs.get("size")
        if size in VALID_SIZES:
            params["size"] = size

        # Pexels accepts named colours or any hex code, so this is passed
        # through as given rather than validated against a fixed list.
        if kwargs.get("color"):
            params["color"] = kwargs["color"]
        if kwargs.get("locale"):
            params["locale"] = kwargs["locale"]

        data = await self.request_json("/search", params)
        return [self._to_result(photo) for photo in data.get("photos", [])]

    async def get_details(self, image_id: str) -> ImageResult | None:
        """Fetch one photo by id."""
        photo_id = self.strip_prefix(image_id)
        data = await self.request_json(f"/photos/{photo_id}")
        return self._to_result(data)

    def _to_result(self, photo: dict[str, Any]) -> ImageResult:
        """Convert a Pexels photo object into an :class:`ImageResult`."""
        src = photo.get("src") or {}
        sizes = {
            canonical: src[pexels_key]
            for canonical, pexels_key in SIZE_MAP.items()
            if src.get(pexels_key)
        }
        # Preserve the variants that have no canonical equivalent.
        sizes.update({key: src[key] for key in EXTRA_SIZES if src.get(key)})

        alt = (photo.get("alt") or "").strip()
        photographer = photo.get("photographer") or "Unknown"

        return ImageResult(
            id=f"{self.name}_{photo['id']}",
            title=alt or f"Photo by {photographer}",
            description=alt or None,
            url=src.get("large") or src.get("original") or "",
            thumbnail=src.get("medium") or src.get("tiny") or "",
            width=photo.get("width", 0),
            height=photo.get("height", 0),
            photographer=photographer,
            photographer_url=photo.get("photographer_url"),
            source="Pexels",
            license=LICENSE,
            # The Pexels photo page, which their guidelines require linking to.
            attribution_url=photo.get("url"),
            tags=[alt.lower()] if alt else [],
            sizes=sizes,
        )

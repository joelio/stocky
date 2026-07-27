"""Data models shared across providers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Canonical size names Stocky exposes, smallest first. Providers map their own
# size variants onto these so callers get one vocabulary across sources.
SIZE_NAMES = ("thumbnail", "small", "medium", "large", "original")


@dataclass
class ImageResult:
    """A single image search result with its metadata.

    ``sizes`` maps the canonical names in :data:`SIZE_NAMES` to direct URLs.
    Keeping the full set matters for downloads: the previous implementation
    stored only ``url`` and ``thumbnail`` and then tried to reconstruct the
    original by string-replacing query parameters, which broke whenever a
    provider changed its URL format.
    """

    id: str
    title: str
    description: str | None
    url: str
    thumbnail: str
    width: int
    height: int
    photographer: str
    photographer_url: str | None
    source: str
    license: str
    attribution_url: str | None = None
    tags: list[str] = field(default_factory=list)
    sizes: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalise mutable fields that callers may pass as ``None``."""
        if self.tags is None:
            self.tags = []
        if self.sizes is None:
            self.sizes = {}

    @property
    def provider(self) -> str:
        """Provider key parsed from the prefixed id, e.g. ``"pexels"``."""
        return self.id.split("_", 1)[0]

    def url_for_size(self, size: str) -> str | None:
        """Return the URL for ``size``, falling back sensibly when absent.

        Not every provider offers every size. Rather than fail, walk down from
        the requested size towards smaller ones, then back up, so a caller
        always gets the closest available image.
        """
        if size in self.sizes:
            return self.sizes[size]

        if size not in SIZE_NAMES:
            return None

        index = SIZE_NAMES.index(size)
        # Prefer the next smaller size, then progressively larger ones.
        for candidate in reversed(SIZE_NAMES[:index]):
            if candidate in self.sizes:
                return self.sizes[candidate]
        for candidate in SIZE_NAMES[index + 1:]:
            if candidate in self.sizes:
                return self.sizes[candidate]
        return self.url or None

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dictionary suitable for a JSON tool response."""
        return asdict(self)

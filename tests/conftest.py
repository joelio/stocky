"""Shared fixtures and provider response fixtures.

The sample payloads mirror the real API responses field-for-field, including
the parts that are easy to get wrong: Unsplash's frequently-null
``description``, its slug-based ``links.html``, and Pexels' eight ``src``
variants rather than the five that are obvious from the docs.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from stocky_mcp.config import Config

PEXELS_PHOTO: dict[str, Any] = {
    "id": 67762,
    "width": 5184,
    "height": 3456,
    "url": "https://www.pexels.com/photo/silhouette-of-a-tree-67762/",
    "photographer": "Sabeel Ahammed",
    "photographer_url": "https://www.pexels.com/@sabeel-ahammed-15010",
    "photographer_id": 15010,
    "avg_color": "#4B606A",
    "src": {
        "original": "https://images.pexels.com/photos/67762/photo.jpeg",
        "large2x": "https://images.pexels.com/photos/67762/photo.jpeg?dpr=2&h=650&w=940",
        "large": "https://images.pexels.com/photos/67762/photo.jpeg?h=650&w=940",
        "medium": "https://images.pexels.com/photos/67762/photo.jpeg?h=350",
        "small": "https://images.pexels.com/photos/67762/photo.jpeg?h=130",
        "portrait": "https://images.pexels.com/photos/67762/photo.jpeg?h=1200&w=800",
        "landscape": "https://images.pexels.com/photos/67762/photo.jpeg?h=627&w=1200",
        "tiny": "https://images.pexels.com/photos/67762/photo.jpeg?h=200&w=280",
    },
    "liked": False,
    "alt": "Silhouette of a Barren Tree",
}

PEXELS_SEARCH: dict[str, Any] = {
    "page": 1,
    "per_page": 15,
    "total_results": 10000,
    "photos": [PEXELS_PHOTO],
    "next_page": "https://api.pexels.com/v1/search/?page=2",
}

UNSPLASH_PHOTO: dict[str, Any] = {
    "id": "DXEhDakyt8E",
    "slug": "a-deer-walks-through-a-forest-DXEhDakyt8E",
    "created_at": "2024-03-01T10:00:00Z",
    "width": 6000,
    "height": 4000,
    "color": "#264026",
    "blur_hash": "LAB|_a00~q00Rj",
    # Author captions are very often null on Unsplash; alt_description is not.
    "description": None,
    "alt_description": "a deer walks through a forest",
    "asset_type": "photo",
    "urls": {
        "raw": "https://images.unsplash.com/photo-1?ixid=abc&ixlib=rb-4.1.0",
        "full": "https://images.unsplash.com/photo-1?ixid=abc&q=85&fm=jpg",
        "regular": "https://images.unsplash.com/photo-1?ixid=abc&w=1080",
        "small": "https://images.unsplash.com/photo-1?ixid=abc&w=400",
        "thumb": "https://images.unsplash.com/photo-1?ixid=abc&w=200",
    },
    "links": {
        "self": "https://api.unsplash.com/photos/a-deer-DXEhDakyt8E",
        "html": "https://unsplash.com/photos/a-deer-walks-DXEhDakyt8E",
        "download": "https://unsplash.com/photos/DXEhDakyt8E/download?ixid=abc",
        "download_location": (
            "https://api.unsplash.com/photos/DXEhDakyt8E/download?ixid=abc"
        ),
    },
    "user": {
        "id": "user1",
        "username": "emmakphoto",
        "name": "Emma K",
        "links": {"html": "https://unsplash.com/@emmakphoto"},
    },
    "tags": [{"title": "deer"}, {"title": "forest"}],
}

UNSPLASH_SEARCH: dict[str, Any] = {
    "total": 133,
    "total_pages": 7,
    "results": [UNSPLASH_PHOTO],
}


def json_response(
    payload: Any,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Build an httpx JSON response for a MockTransport handler."""
    return httpx.Response(
        status_code,
        content=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
    )


def make_transport(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.MockTransport:
    """Wrap ``handler`` in a MockTransport."""
    return httpx.MockTransport(handler)


class RecordingTransport(httpx.MockTransport):
    """A MockTransport that records every request it handled.

    Lets tests assert on the URLs and query parameters actually sent, which is
    where most provider bugs live (wrong parameter name, unclamped per_page,
    a filter silently dropped).
    """

    def __init__(
        self,
        handler: Callable[[httpx.Request], httpx.Response],
    ) -> None:
        self.requests: list[httpx.Request] = []

        def recording_handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return handler(request)

        super().__init__(recording_handler)

    @property
    def last_request(self) -> httpx.Request:
        """The most recent request, for convenient assertions."""
        assert self.requests, "no request was made"
        return self.requests[-1]


@pytest.fixture
def pexels_transport() -> RecordingTransport:
    """A transport serving canned Pexels search and photo responses."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "/search" in request.url.path:
            return json_response(PEXELS_SEARCH)
        if "/photos/" in request.url.path:
            return json_response(PEXELS_PHOTO)
        return json_response({"error": "unexpected path"}, 404)

    return RecordingTransport(handler)


@pytest.fixture
def unsplash_transport() -> RecordingTransport:
    """A transport serving canned Unsplash search and photo responses."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "/search/photos" in request.url.path:
            return json_response(UNSPLASH_SEARCH)
        if request.url.path.endswith("/download"):
            return json_response({"url": "https://images.unsplash.com/photo-1"})
        if "/photos/" in request.url.path:
            return json_response(UNSPLASH_PHOTO)
        return json_response({"errors": ["not found"]}, 404)

    return RecordingTransport(handler)


@pytest.fixture
def both_providers_transport() -> RecordingTransport:
    """A transport that serves whichever provider a request is aimed at."""

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if "pexels" in host:
            if "/search" in request.url.path:
                return json_response(PEXELS_SEARCH)
            return json_response(PEXELS_PHOTO)
        if "/search/photos" in request.url.path:
            return json_response(UNSPLASH_SEARCH)
        if request.url.path.endswith("/download"):
            return json_response({"url": "https://images.unsplash.com/photo-1"})
        return json_response(UNSPLASH_PHOTO)

    return RecordingTransport(handler)


@pytest.fixture
def config() -> Config:
    """A configuration with both providers credentialled and caching off."""
    return Config(
        pexels_api_key="test-pexels-key",
        unsplash_access_key="test-unsplash-key",
        cache_ttl=0,
    )

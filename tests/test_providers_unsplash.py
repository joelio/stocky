"""Tests for the Unsplash provider."""

from __future__ import annotations

import httpx
import pytest

from stocky_mcp.errors import ProviderAuthError, ProviderRateLimitError
from stocky_mcp.providers.unsplash import MAX_PER_PAGE, UnsplashProvider

from .conftest import UNSPLASH_PHOTO, RecordingTransport, json_response


def build(transport: httpx.MockTransport) -> UnsplashProvider:
    return UnsplashProvider("test-key", transport=transport)


async def test_search_returns_mapped_results(
    unsplash_transport: RecordingTransport,
) -> None:
    async with build(unsplash_transport) as provider:
        results = await provider.search("deer")

    assert len(results) == 1
    result = results[0]
    assert result.id == "unsplash_DXEhDakyt8E"
    assert result.provider == "unsplash"
    assert result.photographer == "Emma K"
    assert result.photographer_url == "https://unsplash.com/@emmakphoto"
    assert result.source == "Unsplash"
    assert result.tags == ["deer", "forest"]


async def test_null_description_falls_back_to_alt_description(
    unsplash_transport: RecordingTransport,
) -> None:
    """Unsplash's `description` is the author's caption and is usually null."""
    async with build(unsplash_transport) as provider:
        results = await provider.search("deer")

    assert UNSPLASH_PHOTO["description"] is None
    assert results[0].title == "a deer walks through a forest"
    assert results[0].description == "a deer walks through a forest"


async def test_author_caption_wins_when_present() -> None:
    photo = {**UNSPLASH_PHOTO, "description": "Winter morning"}
    transport = RecordingTransport(lambda _: json_response({"results": [photo]}))

    async with build(transport) as provider:
        results = await provider.search("deer")

    assert results[0].title == "Winter morning"


async def test_title_falls_back_to_photographer_when_both_absent() -> None:
    photo = {**UNSPLASH_PHOTO, "description": None, "alt_description": None}
    transport = RecordingTransport(lambda _: json_response({"results": [photo]}))

    async with build(transport) as provider:
        results = await provider.search("deer")

    assert results[0].title == "Photo by Emma K"


async def test_per_page_is_clamped_to_thirty(
    unsplash_transport: RecordingTransport,
) -> None:
    """Above 30, Unsplash silently falls back to 10 — so 50 would return FEWER
    images than 30. Clamping client-side is required, not cosmetic."""
    async with build(unsplash_transport) as provider:
        await provider.search("deer", per_page=50)

    params = unsplash_transport.last_request.url.params
    assert params["per_page"] == str(MAX_PER_PAGE)


async def test_sort_is_sent_as_order_by(
    unsplash_transport: RecordingTransport,
) -> None:
    async with build(unsplash_transport) as provider:
        await provider.search("deer", sort="latest")

    assert unsplash_transport.last_request.url.params["order_by"] == "latest"


async def test_deprecated_sort_value_is_dropped(
    unsplash_transport: RecordingTransport,
) -> None:
    """`popular` still returns 200 but was deprecated in 2020."""
    async with build(unsplash_transport) as provider:
        await provider.search("deer", sort="popular")

    assert "order_by" not in unsplash_transport.last_request.url.params


async def test_square_orientation_is_translated_to_squarish(
    unsplash_transport: RecordingTransport,
) -> None:
    """Pexels says 'square', Unsplash says 'squarish'. Callers say 'square'."""
    async with build(unsplash_transport) as provider:
        await provider.search("deer", orientation="square")

    assert unsplash_transport.last_request.url.params["orientation"] == "squarish"


async def test_invalid_orientation_is_dropped(
    unsplash_transport: RecordingTransport,
) -> None:
    """Unsplash rejects bad enums with 400, so they must not be forwarded."""
    async with build(unsplash_transport) as provider:
        await provider.search("deer", orientation="diagonal")

    assert "orientation" not in unsplash_transport.last_request.url.params


async def test_invalid_colour_is_dropped(
    unsplash_transport: RecordingTransport,
) -> None:
    async with build(unsplash_transport) as provider:
        await provider.search("deer", color="chartreuse")

    assert "color" not in unsplash_transport.last_request.url.params


async def test_valid_colour_is_forwarded(
    unsplash_transport: RecordingTransport,
) -> None:
    async with build(unsplash_transport) as provider:
        await provider.search("deer", color="black_and_white")

    assert unsplash_transport.last_request.url.params["color"] == "black_and_white"


async def test_sizes_are_mapped_from_urls(
    unsplash_transport: RecordingTransport,
) -> None:
    async with build(unsplash_transport) as provider:
        results = await provider.search("deer")

    sizes = results[0].sizes
    assert sizes["thumbnail"] == UNSPLASH_PHOTO["urls"]["thumb"]
    assert sizes["medium"] == UNSPLASH_PHOTO["urls"]["regular"]
    assert sizes["original"] == UNSPLASH_PHOTO["urls"]["raw"]


async def test_ixid_is_preserved_in_urls(
    unsplash_transport: RecordingTransport,
) -> None:
    """Stripping ixid from a hotlinked URL breaks Unsplash attribution."""
    async with build(unsplash_transport) as provider:
        results = await provider.search("deer")

    assert all("ixid=abc" in url for url in results[0].sizes.values())


async def test_auth_header_uses_client_id_scheme(
    unsplash_transport: RecordingTransport,
) -> None:
    async with build(unsplash_transport) as provider:
        await provider.search("deer")

    headers = unsplash_transport.last_request.headers
    assert headers["Authorization"] == "Client-ID test-key"
    assert headers["Accept-Version"] == "v1"


async def test_rate_limit_is_detected_from_403_plus_header() -> None:
    """Unsplash returns 403, not 429, when the hourly quota is exhausted."""
    transport = RecordingTransport(
        lambda _: json_response(
            {"errors": ["Rate Limit Exceeded"]},
            403,
            headers={"X-Ratelimit-Remaining": "0"},
        )
    )

    async with build(transport) as provider:
        with pytest.raises(ProviderRateLimitError):
            await provider.search("deer")


async def test_plain_403_is_still_an_auth_error() -> None:
    """Without the exhausted-quota header, 403 means a bad key."""
    transport = RecordingTransport(
        lambda _: json_response(
            {"errors": ["OAuth error: The access token is invalid"]},
            403,
            headers={"X-Ratelimit-Remaining": "42"},
        )
    )

    async with build(transport) as provider:
        with pytest.raises(ProviderAuthError):
            await provider.search("deer")


async def test_401_is_an_auth_error_and_surfaces_the_message() -> None:
    transport = RecordingTransport(
        lambda _: json_response(
            {"errors": ["OAuth error: The access token is invalid"]}, 401
        )
    )

    async with build(transport) as provider:
        with pytest.raises(ProviderAuthError, match="access token is invalid"):
            await provider.search("deer")


async def test_error_list_is_joined_into_the_message() -> None:
    transport = RecordingTransport(
        lambda _: json_response({"errors": ["a is missing", "b is empty"]}, 400)
    )

    async with build(transport) as provider:
        with pytest.raises(Exception, match="a is missing; b is empty"):
            await provider.search("deer")


async def test_trigger_download_returns_the_resolved_url(
    unsplash_transport: RecordingTransport,
) -> None:
    async with build(unsplash_transport) as provider:
        url = await provider.trigger_download(
            "https://api.unsplash.com/photos/DXEhDakyt8E/download?ixid=abc"
        )

    assert url == "https://images.unsplash.com/photo-1"


async def test_trigger_download_uses_the_location_verbatim(
    unsplash_transport: RecordingTransport,
) -> None:
    """The ixid query parameter must survive; it must not be reconstructed."""
    location = "https://api.unsplash.com/photos/DXEhDakyt8E/download?ixid=abc"

    async with build(unsplash_transport) as provider:
        await provider.trigger_download(location)

    assert unsplash_transport.last_request.url.params["ixid"] == "abc"


async def test_trigger_download_ignores_an_empty_location(
    unsplash_transport: RecordingTransport,
) -> None:
    async with build(unsplash_transport) as provider:
        assert await provider.trigger_download("") is None

    assert unsplash_transport.requests == []


async def test_failed_download_ping_does_not_raise() -> None:
    """A broken compliance counter must never block the user's download."""
    transport = RecordingTransport(lambda _: json_response({"errors": ["nope"]}, 500))

    async with build(transport) as provider:
        assert await provider.trigger_download("https://api.unsplash.com/x") is None


async def test_missing_key_is_rejected_with_guidance() -> None:
    with pytest.raises(ValueError, match="UNSPLASH_ACCESS_KEY"):
        UnsplashProvider("")


async def test_get_details_strips_the_prefix(
    unsplash_transport: RecordingTransport,
) -> None:
    async with build(unsplash_transport) as provider:
        await provider.get_details("unsplash_DXEhDakyt8E")

    assert unsplash_transport.last_request.url.path.endswith("/photos/DXEhDakyt8E")


async def test_ids_containing_underscores_survive_prefix_stripping(
    unsplash_transport: RecordingTransport,
) -> None:
    """Unsplash ids may contain underscores; only the provider prefix goes."""
    async with build(unsplash_transport) as provider:
        await provider.get_details("unsplash_a_b_c")

    assert unsplash_transport.last_request.url.path.endswith("/photos/a_b_c")


async def test_tags_without_titles_are_skipped() -> None:
    photo = {**UNSPLASH_PHOTO, "tags": [{"title": "deer"}, {}, "bad"]}
    transport = RecordingTransport(lambda _: json_response({"results": [photo]}))

    async with build(transport) as provider:
        results = await provider.search("deer")

    assert results[0].tags == ["deer"]

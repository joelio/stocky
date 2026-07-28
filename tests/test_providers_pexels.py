"""Tests for the Pexels provider."""

from __future__ import annotations

import httpx
import pytest

from stocky_mcp.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from stocky_mcp.providers.pexels import MAX_PER_PAGE, PexelsProvider

from .conftest import PEXELS_PHOTO, RecordingTransport, json_response


def build(transport: httpx.MockTransport) -> PexelsProvider:
    return PexelsProvider("test-key", transport=transport)


async def test_search_returns_mapped_results(
    pexels_transport: RecordingTransport,
) -> None:
    async with build(pexels_transport) as provider:
        results = await provider.search("trees")

    assert len(results) == 1
    result = results[0]
    assert result.id == "pexels_67762"
    assert result.provider == "pexels"
    assert result.title == "Silhouette of a Barren Tree"
    assert result.photographer == "Sabeel Ahammed"
    assert result.source == "Pexels"
    assert result.width == 5184


async def test_search_sends_the_query(pexels_transport: RecordingTransport) -> None:
    async with build(pexels_transport) as provider:
        await provider.search("misty forest")

    assert pexels_transport.last_request.url.params["query"] == "misty forest"


async def test_per_page_is_clamped_to_the_api_maximum(
    pexels_transport: RecordingTransport,
) -> None:
    """Pexels clamps to 80 server-side; doing it here keeps the reply honest."""
    async with build(pexels_transport) as provider:
        await provider.search("trees", per_page=500)

    params = pexels_transport.last_request.url.params
    assert params["per_page"] == str(MAX_PER_PAGE)


async def test_per_page_below_one_is_raised_to_one(
    pexels_transport: RecordingTransport,
) -> None:
    async with build(pexels_transport) as provider:
        await provider.search("trees", per_page=0)

    assert pexels_transport.last_request.url.params["per_page"] == "1"


async def test_page_below_one_is_raised_to_one(
    pexels_transport: RecordingTransport,
) -> None:
    async with build(pexels_transport) as provider:
        await provider.search("trees", page=-3)

    assert pexels_transport.last_request.url.params["page"] == "1"


async def test_valid_orientation_is_forwarded(
    pexels_transport: RecordingTransport,
) -> None:
    async with build(pexels_transport) as provider:
        await provider.search("trees", orientation="landscape")

    assert pexels_transport.last_request.url.params["orientation"] == "landscape"


async def test_invalid_orientation_is_dropped(
    pexels_transport: RecordingTransport,
) -> None:
    """Pexels ignores bad filters and still returns 200, hiding the mistake."""
    async with build(pexels_transport) as provider:
        await provider.search("trees", orientation="diagonal")

    assert "orientation" not in pexels_transport.last_request.url.params


async def test_hex_colour_is_forwarded(pexels_transport: RecordingTransport) -> None:
    """Pexels accepts hex codes as well as names, so colours pass through."""
    async with build(pexels_transport) as provider:
        await provider.search("trees", color="#ff0000")

    assert pexels_transport.last_request.url.params["color"] == "#ff0000"


async def test_unset_filters_are_not_sent(
    pexels_transport: RecordingTransport,
) -> None:
    async with build(pexels_transport) as provider:
        await provider.search("trees", orientation=None, color=None)

    params = pexels_transport.last_request.url.params
    assert "color" not in params
    assert "orientation" not in params


async def test_all_canonical_sizes_are_captured(
    pexels_transport: RecordingTransport,
) -> None:
    async with build(pexels_transport) as provider:
        results = await provider.search("trees")

    sizes = results[0].sizes
    assert sizes["thumbnail"] == PEXELS_PHOTO["src"]["tiny"]
    assert sizes["small"] == PEXELS_PHOTO["src"]["small"]
    assert sizes["medium"] == PEXELS_PHOTO["src"]["medium"]
    assert sizes["large"] == PEXELS_PHOTO["src"]["large"]
    assert sizes["original"] == PEXELS_PHOTO["src"]["original"]


async def test_extra_pexels_variants_are_preserved(
    pexels_transport: RecordingTransport,
) -> None:
    """large2x, portrait and landscape have no canonical name but are useful."""
    async with build(pexels_transport) as provider:
        results = await provider.search("trees")

    assert results[0].sizes["large2x"] == PEXELS_PHOTO["src"]["large2x"]
    assert "portrait" in results[0].sizes
    assert "landscape" in results[0].sizes


async def test_attribution_url_is_the_photo_page(
    pexels_transport: RecordingTransport,
) -> None:
    """Pexels' guidelines require linking back to the photo page."""
    async with build(pexels_transport) as provider:
        results = await provider.search("trees")

    assert results[0].attribution_url == PEXELS_PHOTO["url"]


async def test_search_attribution_matches_details_attribution(
    pexels_transport: RecordingTransport,
) -> None:
    """The old code set attribution on details but not on search results."""
    async with build(pexels_transport) as provider:
        searched = (await provider.search("trees"))[0]
        detailed = await provider.get_details("pexels_67762")

    assert detailed is not None
    assert searched.attribution_url == detailed.attribution_url


async def test_get_details_strips_the_prefix(
    pexels_transport: RecordingTransport,
) -> None:
    async with build(pexels_transport) as provider:
        await provider.get_details("pexels_67762")

    assert pexels_transport.last_request.url.path.endswith("/photos/67762")


async def test_empty_photo_list_returns_no_results() -> None:
    transport = RecordingTransport(lambda _: json_response({"photos": []}))

    async with build(transport) as provider:
        assert await provider.search("nothing at all") == []


async def test_missing_alt_falls_back_to_a_photographer_title() -> None:
    photo = {**PEXELS_PHOTO, "alt": ""}
    transport = RecordingTransport(lambda _: json_response({"photos": [photo]}))

    async with build(transport) as provider:
        results = await provider.search("trees")

    assert results[0].title == "Photo by Sabeel Ahammed"
    assert results[0].description is None
    assert results[0].tags == []


async def test_user_agent_header_is_sent(
    pexels_transport: RecordingTransport,
) -> None:
    """Pexels' edge returns 403 to requests without a User-Agent."""
    async with build(pexels_transport) as provider:
        await provider.search("trees")

    assert pexels_transport.last_request.headers["User-Agent"] == "stocky-mcp"


async def test_api_key_is_sent_raw_without_a_scheme(
    pexels_transport: RecordingTransport,
) -> None:
    async with build(pexels_transport) as provider:
        await provider.search("trees")

    assert pexels_transport.last_request.headers["Authorization"] == "test-key"


async def test_missing_key_is_rejected_with_guidance() -> None:
    with pytest.raises(ValueError, match="PEXELS_API_KEY"):
        PexelsProvider("")


async def test_use_outside_context_manager_is_an_error() -> None:
    provider = PexelsProvider("test-key")

    with pytest.raises(RuntimeError, match="async context manager"):
        await provider.search("trees")


async def test_client_is_closed_on_exit(
    pexels_transport: RecordingTransport,
) -> None:
    provider = build(pexels_transport)
    async with provider:
        pass

    with pytest.raises(RuntimeError):
        _ = provider.client


@pytest.mark.parametrize("status", [401, 403])
async def test_auth_failures_raise_auth_error(status: int) -> None:
    transport = RecordingTransport(
        lambda _: json_response(
            {"status": status, "code": "Unauthorized", "message": "Missing API key"},
            status,
        )
    )

    async with build(transport) as provider:
        with pytest.raises(ProviderAuthError) as exc_info:
            await provider.search("trees")

    assert exc_info.value.provider == "pexels"
    assert exc_info.value.status_code == status
    assert "Missing API key" in str(exc_info.value)


async def test_rate_limit_raises_rate_limit_error() -> None:
    """Pexels uses 429, unlike Unsplash which uses 403."""
    transport = RecordingTransport(lambda _: json_response({}, 429))

    async with build(transport) as provider:
        with pytest.raises(ProviderRateLimitError):
            await provider.search("trees")


async def test_not_found_raises_not_found_error() -> None:
    transport = RecordingTransport(
        lambda _: json_response({"status": 404, "code": "Not Found"}, 404)
    )

    async with build(transport) as provider:
        with pytest.raises(ProviderNotFoundError):
            await provider.get_details("pexels_1")


async def test_server_error_raises_provider_error() -> None:
    transport = RecordingTransport(lambda _: httpx.Response(500, text="boom"))

    async with build(transport) as provider:
        with pytest.raises(ProviderError) as exc_info:
            await provider.search("trees")

    assert exc_info.value.status_code == 500


async def test_timeout_raises_timeout_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("too slow", request=request)

    async with build(RecordingTransport(handler)) as provider:
        with pytest.raises(ProviderTimeoutError, match="timed out"):
            await provider.search("trees")


async def test_transport_error_raises_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    async with build(RecordingTransport(handler)) as provider:
        with pytest.raises(ProviderError, match="request failed"):
            await provider.search("trees")


async def test_malformed_json_raises_provider_error() -> None:
    transport = RecordingTransport(lambda _: httpx.Response(200, text="not json"))

    async with build(transport) as provider:
        with pytest.raises(ProviderError, match="malformed JSON"):
            await provider.search("trees")


async def test_non_object_json_raises_provider_error() -> None:
    """A bare list is what the old code hit as \"'list' object can't be awaited\"."""
    transport = RecordingTransport(lambda _: json_response([1, 2, 3]))

    async with build(transport) as provider:
        with pytest.raises(ProviderError, match="unexpected JSON"):
            await provider.search("trees")

"""Tests for the provider manager."""

from __future__ import annotations

import base64
from pathlib import Path

import httpx

from stocky_mcp.config import Config
from stocky_mcp.manager import StockImageManager

from .conftest import (
    PEXELS_PHOTO,
    PEXELS_SEARCH,
    UNSPLASH_PHOTO,
    UNSPLASH_SEARCH,
    RecordingTransport,
    json_response,
)


def make_manager(
    transport: httpx.MockTransport,
    **config_overrides: object,
) -> StockImageManager:
    """Build a manager with both providers credentialled."""
    defaults: dict[str, object] = {
        "pexels_api_key": "pk",
        "unsplash_access_key": "uk",
        "cache_ttl": 0,
    }
    defaults.update(config_overrides)
    return StockImageManager(Config(**defaults), transport=transport)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Provider selection
# --------------------------------------------------------------------------


async def test_no_credentials_yields_a_configuration_error() -> None:
    manager = StockImageManager(Config())

    result = await manager.search("trees")

    assert "error" in result
    assert "PEXELS_API_KEY" in result["error"]
    assert result["results"] == {}


async def test_only_credentialled_providers_are_created() -> None:
    manager = StockImageManager(Config(pexels_api_key="pk"))

    assert manager.available_providers == ["pexels"]


async def test_searches_all_configured_providers_by_default(
    both_providers_transport: RecordingTransport,
) -> None:
    manager = make_manager(both_providers_transport)

    result = await manager.search("trees")

    assert set(result["results"]) == {"pexels", "unsplash"}
    assert result["total_results"] == 2


async def test_provider_subset_is_respected(
    both_providers_transport: RecordingTransport,
) -> None:
    manager = make_manager(both_providers_transport)

    result = await manager.search("trees", providers=["pexels"])

    assert set(result["results"]) == {"pexels"}


async def test_unknown_provider_names_are_reported() -> None:
    manager = StockImageManager(Config(pexels_api_key="pk"))

    result = await manager.search("trees", providers=["flickr"])

    assert "error" in result
    assert "flickr" in result["error"]


async def test_unconfigured_provider_is_filtered_out(
    pexels_transport: RecordingTransport,
) -> None:
    manager = StockImageManager(
        Config(pexels_api_key="pk", cache_ttl=0), transport=pexels_transport
    )

    result = await manager.search("trees", providers=["pexels", "unsplash"])

    assert set(result["results"]) == {"pexels"}


# --------------------------------------------------------------------------
# Error isolation
# --------------------------------------------------------------------------


async def test_one_failing_provider_does_not_break_the_other() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "pexels" in request.url.host:
            return json_response({"errors": ["boom"]}, 500)
        return json_response(UNSPLASH_SEARCH)

    manager = make_manager(RecordingTransport(handler))
    result = await manager.search("trees")

    assert result["results"]["pexels"] == []
    assert len(result["results"]["unsplash"]) == 1
    assert "pexels" in result["errors"]


async def test_auth_failure_is_reported_rather_than_looking_empty() -> None:
    """The old code returned [] for auth errors, hiding broken credentials."""
    transport = RecordingTransport(
        lambda _: json_response({"message": "Missing API key"}, 401)
    )
    manager = make_manager(transport)

    result = await manager.search("trees")

    assert "errors" in result
    assert "rejected the API key" in result["errors"]["pexels"]


async def test_successful_search_has_no_errors_key(
    both_providers_transport: RecordingTransport,
) -> None:
    manager = make_manager(both_providers_transport)

    assert "errors" not in await manager.search("trees")


# --------------------------------------------------------------------------
# Caching
# --------------------------------------------------------------------------


async def test_repeated_search_is_served_from_cache(
    both_providers_transport: RecordingTransport,
) -> None:
    manager = make_manager(both_providers_transport, cache_ttl=300)

    await manager.search("trees")
    first_count = len(both_providers_transport.requests)
    await manager.search("trees")

    assert len(both_providers_transport.requests) == first_count
    assert manager.cache.hits == 1


async def test_cache_key_ignores_provider_order(
    both_providers_transport: RecordingTransport,
) -> None:
    manager = make_manager(both_providers_transport, cache_ttl=300)

    await manager.search("trees", providers=["pexels", "unsplash"])
    count = len(both_providers_transport.requests)
    await manager.search("trees", providers=["unsplash", "pexels"])

    assert len(both_providers_transport.requests) == count


async def test_cache_key_is_case_insensitive(
    both_providers_transport: RecordingTransport,
) -> None:
    manager = make_manager(both_providers_transport, cache_ttl=300)

    await manager.search("Trees")
    count = len(both_providers_transport.requests)
    await manager.search("trees")

    assert len(both_providers_transport.requests) == count


async def test_different_pages_are_cached_separately(
    both_providers_transport: RecordingTransport,
) -> None:
    manager = make_manager(both_providers_transport, cache_ttl=300)

    await manager.search("trees", page=1)
    count = len(both_providers_transport.requests)
    await manager.search("trees", page=2)

    assert len(both_providers_transport.requests) > count


async def test_different_filters_are_cached_separately(
    both_providers_transport: RecordingTransport,
) -> None:
    manager = make_manager(both_providers_transport, cache_ttl=300)

    await manager.search("trees", orientation="landscape")
    count = len(both_providers_transport.requests)
    await manager.search("trees", orientation="portrait")

    assert len(both_providers_transport.requests) > count


async def test_failed_searches_are_not_cached() -> None:
    """Caching a transient auth failure would serve it for the whole TTL."""
    transport = RecordingTransport(lambda _: json_response({"message": "no"}, 401))
    manager = make_manager(transport, cache_ttl=300)

    await manager.search("trees")
    count = len(transport.requests)
    await manager.search("trees")

    assert len(transport.requests) > count


async def test_zero_ttl_disables_caching(
    both_providers_transport: RecordingTransport,
) -> None:
    manager = make_manager(both_providers_transport, cache_ttl=0)

    await manager.search("trees")
    count = len(both_providers_transport.requests)
    await manager.search("trees")

    assert len(both_providers_transport.requests) > count


async def test_attribution_preference_does_not_leak_through_the_cache(
    both_providers_transport: RecordingTransport,
) -> None:
    """A cached payload is shared, so mutating it would leak between callers."""
    manager = make_manager(both_providers_transport, cache_ttl=300)

    with_attr = await manager.search("trees", include_attribution=True)
    without_attr = await manager.search("trees", include_attribution=False)
    again_with_attr = await manager.search("trees", include_attribution=True)

    assert "attribution" in with_attr["results"]["pexels"][0]
    assert "attribution" not in without_attr["results"]["pexels"][0]
    assert "attribution" in again_with_attr["results"]["pexels"][0]


# --------------------------------------------------------------------------
# Attribution
# --------------------------------------------------------------------------


async def test_attribution_is_omitted_by_default(
    both_providers_transport: RecordingTransport,
) -> None:
    manager = make_manager(both_providers_transport)

    result = await manager.search("trees")

    assert result["results"]["pexels"][0]["attribution_url"] is None


async def test_environment_default_enables_attribution(
    both_providers_transport: RecordingTransport,
) -> None:
    manager = make_manager(both_providers_transport, enable_attribution=True)

    result = await manager.search("trees")

    assert result["results"]["pexels"][0]["attribution"]["text"]


async def test_explicit_parameter_overrides_the_environment(
    both_providers_transport: RecordingTransport,
) -> None:
    manager = make_manager(both_providers_transport, enable_attribution=True)

    result = await manager.search("trees", include_attribution=False)

    assert "attribution" not in result["results"]["pexels"][0]


# --------------------------------------------------------------------------
# Details
# --------------------------------------------------------------------------


async def test_get_details_returns_metadata(
    pexels_transport: RecordingTransport,
) -> None:
    manager = make_manager(pexels_transport)

    result = await manager.get_image_details("pexels_67762")

    assert result["id"] == "pexels_67762"
    assert result["photographer"] == "Sabeel Ahammed"


async def test_get_details_rejects_a_malformed_id(
    pexels_transport: RecordingTransport,
) -> None:
    manager = make_manager(pexels_transport)

    result = await manager.get_image_details("67762")

    assert "Malformed image id" in result["error"]


async def test_get_details_rejects_an_unknown_provider(
    pexels_transport: RecordingTransport,
) -> None:
    manager = make_manager(pexels_transport)

    result = await manager.get_image_details("flickr_123")

    assert "Unknown provider" in result["error"]


async def test_get_details_reports_an_unconfigured_provider() -> None:
    manager = StockImageManager(Config(pexels_api_key="pk"))

    result = await manager.get_image_details("unsplash_abc")

    assert "not configured" in result["error"]


async def test_get_details_surfaces_a_not_found_error() -> None:
    transport = RecordingTransport(lambda _: json_response({"code": "Not Found"}, 404))
    manager = make_manager(transport)

    result = await manager.get_image_details("pexels_1")

    assert "error" in result


# --------------------------------------------------------------------------
# Downloads
# --------------------------------------------------------------------------


IMAGE_BYTES = b"\xff\xd8\xff" + b"jpegdata" * 10


def download_handler(request: httpx.Request) -> httpx.Response:
    """Serve API JSON on api.pexels.com and image bytes elsewhere."""
    if request.url.host.startswith("api."):
        if request.url.path.endswith("/download"):
            return json_response({"url": "https://images.unsplash.com/photo-1"})
        if "/search" in request.url.path:
            return json_response(PEXELS_SEARCH)
        return json_response(PEXELS_PHOTO)
    return httpx.Response(
        200,
        content=IMAGE_BYTES,
        headers={"Content-Type": "image/jpeg", "Content-Length": str(len(IMAGE_BYTES))},
    )


async def test_download_returns_base64_when_no_path_is_given() -> None:
    manager = make_manager(RecordingTransport(download_handler))

    result = await manager.download_image("pexels_67762")

    assert result["success"] is True
    assert base64.b64decode(result["data"]) == IMAGE_BYTES
    assert result["encoding"] == "base64"
    assert result["content_type"] == "image/jpeg"


async def test_download_includes_attribution() -> None:
    """Attribution must travel with the bytes, since the licence requires it."""
    manager = make_manager(RecordingTransport(download_handler))

    result = await manager.download_image("pexels_67762")

    assert "Sabeel Ahammed" in result["attribution"]["text"]


async def test_download_writes_to_disk(tmp_path: Path) -> None:
    manager = make_manager(RecordingTransport(download_handler))
    target = tmp_path / "out.jpg"

    result = await manager.download_image("pexels_67762", output_path=str(target))

    assert result["success"] is True
    assert target.read_bytes() == IMAGE_BYTES


async def test_download_adds_an_extension_when_missing(tmp_path: Path) -> None:
    manager = make_manager(RecordingTransport(download_handler))

    result = await manager.download_image(
        "pexels_67762", output_path=str(tmp_path / "noext")
    )

    assert result["path"].endswith(".jpeg")


async def test_download_creates_parent_directories(tmp_path: Path) -> None:
    manager = make_manager(RecordingTransport(download_handler))
    target = tmp_path / "a" / "b" / "out.jpg"

    await manager.download_image("pexels_67762", output_path=str(target))

    assert target.exists()


async def test_download_uses_the_requested_size() -> None:
    transport = RecordingTransport(download_handler)
    manager = make_manager(transport)

    await manager.download_image("pexels_67762", size="thumbnail")

    image_requests = [r for r in transport.requests if not r.url.host.startswith("api.")]
    assert image_requests[-1].url.params["h"] == "200"


async def test_download_rejects_an_unknown_size() -> None:
    manager = make_manager(RecordingTransport(download_handler))

    result = await manager.download_image("pexels_67762", size="enormous")

    assert "Invalid size" in result["error"]


async def test_download_refuses_a_file_over_the_cap() -> None:
    manager = make_manager(RecordingTransport(download_handler), max_download_bytes=10)

    result = await manager.download_image("pexels_67762")

    assert "limit" in result["error"]


async def test_download_cap_applies_without_content_length() -> None:
    """Content-Length may be absent or wrong, so streaming is checked too."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host.startswith("api."):
            return json_response(PEXELS_PHOTO)
        return httpx.Response(200, content=b"x" * 5000, headers={})

    manager = make_manager(RecordingTransport(handler), max_download_bytes=100)

    result = await manager.download_image("pexels_67762")

    assert "limit" in result["error"]


async def test_download_reports_an_http_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host.startswith("api."):
            return json_response(PEXELS_PHOTO)
        return httpx.Response(404)

    manager = make_manager(RecordingTransport(handler))

    result = await manager.download_image("pexels_67762")

    assert "HTTP 404" in result["error"]


async def test_download_root_confines_writes(tmp_path: Path) -> None:
    """Paths arrive from model-generated tool calls, so traversal is realistic."""
    root = tmp_path / "safe"
    root.mkdir()
    manager = make_manager(RecordingTransport(download_handler), download_root=str(root))

    result = await manager.download_image("pexels_67762", output_path="../escaped.jpg")

    assert "Refusing to write outside" in result["error"]
    assert not (tmp_path / "escaped.jpg").exists()


async def test_download_root_allows_paths_inside_it(tmp_path: Path) -> None:
    root = tmp_path / "safe"
    root.mkdir()
    manager = make_manager(RecordingTransport(download_handler), download_root=str(root))

    result = await manager.download_image("pexels_67762", output_path="ok.jpg")

    assert result["success"] is True
    assert (root / "ok.jpg").exists()


async def test_download_without_a_root_allows_any_path(tmp_path: Path) -> None:
    """Default behaviour is unrestricted, matching the previous release."""
    manager = make_manager(RecordingTransport(download_handler))
    target = tmp_path / "anywhere.jpg"

    result = await manager.download_image("pexels_67762", output_path=str(target))

    assert result["success"] is True


def unsplash_download_handler(request: httpx.Request) -> httpx.Response:
    """Serve Unsplash API JSON, the download ping, and the image bytes."""
    if request.url.path.endswith("/download"):
        return json_response({"url": "https://images.unsplash.com/photo-1"})
    if request.url.host.startswith("api."):
        return json_response(UNSPLASH_PHOTO)
    return httpx.Response(
        200, content=IMAGE_BYTES, headers={"Content-Type": "image/jpeg"}
    )


async def test_unsplash_download_fires_the_compliance_ping() -> None:
    """Unsplash's licence requires reporting downloads to their endpoint."""
    transport = RecordingTransport(unsplash_download_handler)
    manager = make_manager(transport)

    result = await manager.download_image("unsplash_DXEhDakyt8E")

    assert result["success"] is True
    assert any(r.url.path.endswith("/download") for r in transport.requests)


async def test_pexels_download_does_not_ping_unsplash() -> None:
    """The ping is an Unsplash requirement only; Pexels has no equivalent."""
    transport = RecordingTransport(download_handler)
    manager = make_manager(transport)

    await manager.download_image("pexels_67762")

    assert not any(r.url.path.endswith("/download") for r in transport.requests)

"""Regression tests for issues found by adversarial review.

Each test here corresponds to a defect that was proven to exist and has since
been fixed. They are grouped by the concern they guard.
"""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path

import httpx
import pytest

from stocky_mcp.config import Config
from stocky_mcp.errors import ProviderError
from stocky_mcp.manager import StockImageManager
from stocky_mcp.providers.pexels import PexelsProvider

from .conftest import (
    PEXELS_PHOTO,
    PEXELS_SEARCH,
    UNSPLASH_PHOTO,
    RecordingTransport,
    json_response,
)

IMAGE_BYTES = b"\xff\xd8\xff" + b"jpegdata" * 8


def make_manager(
    transport: httpx.MockTransport, **overrides: object
) -> StockImageManager:
    defaults: dict[str, object] = {
        "pexels_api_key": "pk",
        "unsplash_access_key": "uk",
        "cache_ttl": 0,
    }
    defaults.update(overrides)
    return StockImageManager(Config(**defaults), transport=transport)  # type: ignore[arg-type]


def api_and_image_handler(request: httpx.Request) -> httpx.Response:
    """Serve provider JSON on api.* hosts and image bytes elsewhere."""
    if request.url.host.startswith("api."):
        if request.url.path.endswith("/download"):
            return json_response({"url": "https://images.unsplash.com/photo-1"})
        if "/search" in request.url.path:
            return json_response(PEXELS_SEARCH)
        if "unsplash" in request.url.host:
            return json_response(UNSPLASH_PHOTO)
        return json_response(PEXELS_PHOTO)
    return httpx.Response(
        200, content=IMAGE_BYTES, headers={"Content-Type": "image/jpeg"}
    )


# --------------------------------------------------------------------------
# Concurrency
# --------------------------------------------------------------------------


async def test_concurrent_searches_do_not_close_each_others_clients() -> None:
    """Providers used to be shared instances holding one HTTP client.

    The first concurrent operation to finish closed that client, so the others
    failed with "must be used as an async context manager". An MCP server
    dispatches tool calls concurrently, so this was reachable in normal use.
    """
    transport = RecordingTransport(api_and_image_handler)
    manager = make_manager(transport)

    results = await asyncio.gather(
        *(manager.search("trees") for _ in range(6)),
        return_exceptions=True,
    )

    for result in results:
        assert not isinstance(result, BaseException), result
        assert "errors" not in result, result["errors"]


async def test_concurrent_search_and_download_do_not_interfere() -> None:
    transport = RecordingTransport(api_and_image_handler)
    manager = make_manager(transport)

    download, search = await asyncio.gather(
        manager.download_image("pexels_67762"),
        manager.search("trees"),
        return_exceptions=True,
    )

    assert not isinstance(download, BaseException), download
    assert not isinstance(search, BaseException), search
    assert download.get("success") is True, download


async def test_duplicate_provider_names_are_deduplicated() -> None:
    """A repeated name used to issue the same request twice."""
    transport = RecordingTransport(api_and_image_handler)
    manager = make_manager(transport)

    result = await manager.search("trees", providers=["pexels", "pexels"])

    assert result["providers"] == ["pexels"]
    assert len(transport.requests) == 1


# --------------------------------------------------------------------------
# Cache integrity
# --------------------------------------------------------------------------


async def test_mutating_a_result_does_not_corrupt_the_cache() -> None:
    """The copy was shallow, so nested sizes/tags were shared with the cache."""
    transport = RecordingTransport(api_and_image_handler)
    manager = make_manager(transport, cache_ttl=300)

    first = await manager.search("trees", providers=["pexels"])
    item = first["results"]["pexels"][0]
    item["sizes"]["original"] = "https://evil.example/pwned.jpg"
    item["sizes"].pop("thumbnail", None)
    item["tags"].append("MUTATED")
    first["providers"].append("MUTATED")

    second = await manager.search("trees", providers=["pexels"])
    fresh = second["results"]["pexels"][0]

    assert fresh["sizes"]["original"] == PEXELS_PHOTO["src"]["original"]
    assert "thumbnail" in fresh["sizes"]
    assert "MUTATED" not in fresh["tags"]
    assert "MUTATED" not in second["providers"]


async def test_filter_values_cannot_forge_another_cache_key() -> None:
    """Separators in caller text used to make two different searches collide."""
    transport = RecordingTransport(api_and_image_handler)
    manager = make_manager(transport, cache_ttl=300)

    await manager.search(
        "cat", providers=["pexels"], orientation="landscape", color="red"
    )
    after_first = len(transport.requests)

    await manager.search("cat", providers=["pexels"], color="red&orientation=landscape")

    assert len(transport.requests) > after_first, "second search was wrongly cached"


async def test_cache_hit_echoes_the_callers_own_page(
    both_providers_transport: RecordingTransport,
) -> None:
    """A cache hit used to echo the first caller's raw request values."""
    manager = make_manager(both_providers_transport, cache_ttl=300)

    await manager.search("  Misty Forest  ", per_page=20, page=1)
    second = await manager.search("misty forest", per_page=20, page=1)

    assert second["per_page"] == 20
    assert second["page"] == 1


async def test_out_of_range_paging_is_normalised(
    both_providers_transport: RecordingTransport,
) -> None:
    """per_page/page used to be echoed unclamped and keyed separately."""
    manager = make_manager(both_providers_transport, cache_ttl=300)

    first = await manager.search("trees", per_page=500, page=-3)
    after_first = len(both_providers_transport.requests)
    await manager.search("trees", per_page=900, page=-9)

    assert first["per_page"] == 200
    assert first["page"] == 1
    # Both requests normalise to the same thing, so the second is a cache hit.
    assert len(both_providers_transport.requests) == after_first


async def test_empty_provider_list_means_all_configured(
    both_providers_transport: RecordingTransport,
) -> None:
    """A JSON-RPC client cannot reliably distinguish [] from null."""
    manager = make_manager(both_providers_transport)

    result = await manager.search("trees", providers=[])

    assert set(result["results"]) == {"pexels", "unsplash"}


# --------------------------------------------------------------------------
# Errors must never escape a tool
# --------------------------------------------------------------------------


async def test_unexpected_response_shape_returns_an_error_not_an_exception() -> None:
    """A 200 body without 'id' used to raise KeyError out of the tool."""
    transport = RecordingTransport(lambda _: json_response({"status": 522}))
    manager = make_manager(transport)

    details = await manager.get_image_details("pexels_1")
    download = await manager.download_image("pexels_1")

    assert "error" in details
    assert "error" in download


async def test_malformed_image_id_is_rejected_before_the_request() -> None:
    """The id is interpolated into a URL path, so traversal must not reach it."""
    transport = RecordingTransport(api_and_image_handler)
    manager = make_manager(transport)

    result = await manager.get_image_details("pexels_../../v1/collections")

    assert "error" in result
    assert transport.requests == []


@pytest.mark.parametrize(
    "image_id",
    ["unsplash_../../me", "pexels_abc?client_id=leak", "unsplash_a b"],
)
async def test_suspicious_ids_are_refused(image_id: str) -> None:
    transport = RecordingTransport(api_and_image_handler)
    manager = make_manager(transport)

    assert "error" in await manager.get_image_details(image_id)
    assert transport.requests == []


# --------------------------------------------------------------------------
# Download safety
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_path",
    [
        "~/Library/LaunchAgents/evil.plist",
        "/tmp/evil.py",
        "settings.json",
        "notes.sh",
    ],
)
async def test_non_image_extensions_are_refused(bad_path: str) -> None:
    """Without this the tool can plant a file at an attacker-chosen path."""
    manager = make_manager(RecordingTransport(api_and_image_handler))

    result = await manager.download_image("pexels_67762", output_path=bad_path)

    assert "Refusing to write" in result["error"]


async def test_image_extensions_are_allowed(tmp_path: Path) -> None:
    manager = make_manager(RecordingTransport(api_and_image_handler))

    result = await manager.download_image(
        "pexels_67762", output_path=str(tmp_path / "ok.png")
    )

    assert result["success"] is True


async def test_download_to_disk_includes_attribution(tmp_path: Path) -> None:
    """Saving is the act the licences call 'taking' the photo."""
    manager = make_manager(RecordingTransport(api_and_image_handler))

    result = await manager.download_image(
        "pexels_67762", output_path=str(tmp_path / "a.jpg")
    )

    assert "Sabeel Ahammed" in result["attribution"]["text"]


async def test_empty_response_body_is_an_error() -> None:
    """A zero-byte body used to be reported as a successful download."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host.startswith("api."):
            return json_response(PEXELS_PHOTO)
        return httpx.Response(200, content=b"", headers={"Content-Type": "text/html"})

    manager = make_manager(RecordingTransport(handler))

    result = await manager.download_image("pexels_67762")

    assert "empty response" in result["error"]


async def test_image_fetch_does_not_carry_the_api_key() -> None:
    """The provider client sends Authorization on every request; the CDN is a
    different origin that has no business seeing the credential."""
    transport = RecordingTransport(api_and_image_handler)
    manager = make_manager(transport)

    await manager.download_image("pexels_67762")

    image_requests = [r for r in transport.requests if not r.url.host.startswith("api.")]
    assert image_requests, "expected an image fetch"
    for request in image_requests:
        assert "Authorization" not in request.headers


async def test_image_fetch_refuses_compressed_encodings() -> None:
    """Accepting gzip would let a small body decode past the size cap."""
    transport = RecordingTransport(api_and_image_handler)
    manager = make_manager(transport)

    await manager.download_image("pexels_67762")

    image_request = next(
        r for r in transport.requests if not r.url.host.startswith("api.")
    )
    assert image_request.headers["Accept-Encoding"] == "identity"


@pytest.mark.parametrize(
    "hostile_url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://127.0.0.1:6379/",
        "http://10.0.0.5/internal",
        "ftp://example.com/x.jpg",
    ],
)
async def test_private_and_non_http_image_urls_are_refused(hostile_url: str) -> None:
    """httpx ignores base_url for an absolute URL, so a hostile provider
    response could otherwise point the fetch at an internal address."""
    photo = {**PEXELS_PHOTO, "src": {**PEXELS_PHOTO["src"], "original": hostile_url}}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host.startswith("api."):
            return json_response(photo)
        return httpx.Response(200, content=IMAGE_BYTES)

    transport = RecordingTransport(handler)
    manager = make_manager(transport)

    result = await manager.download_image("pexels_67762", size="original")

    assert "Refusing to fetch" in result["error"]
    assert not [r for r in transport.requests if not r.url.host.startswith("api.")]


async def test_unsplash_download_fetches_metadata_only_once() -> None:
    """The compliance ping used to re-fetch the photo, halving the demo-tier
    budget of 50 requests per hour."""
    transport = RecordingTransport(api_and_image_handler)
    manager = make_manager(transport)

    await manager.download_image("unsplash_DXEhDakyt8E")

    photo_fetches = [
        r
        for r in transport.requests
        if r.url.path.startswith("/photos/") and not r.url.path.endswith("/download")
    ]
    assert len(photo_fetches) == 1
    assert any(r.url.path.endswith("/download") for r in transport.requests)


async def test_base64_download_still_works() -> None:
    manager = make_manager(RecordingTransport(api_and_image_handler))

    result = await manager.download_image("pexels_67762")

    assert base64.b64decode(result["data"]) == IMAGE_BYTES


# --------------------------------------------------------------------------
# Provider transport limits
# --------------------------------------------------------------------------


async def test_oversized_json_response_is_refused() -> None:
    """request_json buffered the whole body with no cap, so a compressed
    response could decode into gigabytes."""
    huge = json_response({"photos": [], "junk": "x" * 200_000})
    provider = PexelsProvider(
        "k", transport=RecordingTransport(lambda _: huge), max_json_bytes=1000
    )

    async with provider:
        with pytest.raises(ProviderError, match="exceeded"):
            await provider.search("trees")


async def test_error_detail_is_truncated() -> None:
    transport = RecordingTransport(lambda _: json_response({"message": "e" * 5000}, 500))

    async with PexelsProvider("k", transport=transport) as provider:
        with pytest.raises(ProviderError) as exc_info:
            await provider.search("trees")

    assert len(str(exc_info.value)) < 500


async def test_error_detail_redacts_the_api_key() -> None:
    """Some APIs echo the rejected credential back in the error body."""
    secret = "SECRET_KEY_abcdef"
    transport = RecordingTransport(
        lambda _: json_response({"message": f"Invalid Access Token: {secret}"}, 401)
    )

    async with PexelsProvider(secret, transport=transport) as provider:
        with pytest.raises(ProviderError) as exc_info:
            await provider.search("trees")

    assert secret not in str(exc_info.value)
    assert "redacted" in str(exc_info.value)


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "1e400"])
def test_non_finite_config_values_fall_back_to_defaults(raw: str) -> None:
    """NaN compares False against everything, so it slipped past the minimum
    guard and then crashed int()."""
    config = Config.from_env(
        {
            "STOCKY_CACHE_TTL": raw,
            "STOCKY_HTTP_TIMEOUT": raw,
            "STOCKY_MAX_DOWNLOAD_BYTES": raw,
        }
    )

    assert config.cache_ttl == 300.0
    assert config.http_timeout == 15.0
    assert config.max_download_bytes == 26214400


def test_api_keys_are_not_in_the_config_repr() -> None:
    """Config is a public export, so any downstream log of it would leak."""
    config = Config(pexels_api_key="SECRET_PK", unsplash_access_key="SECRET_UK")

    assert "SECRET_PK" not in repr(config)
    assert "SECRET_UK" not in repr(config)


# --------------------------------------------------------------------------
# Transfer encoding
# --------------------------------------------------------------------------


async def test_gzipped_provider_response_is_decoded_once() -> None:
    """Capping the response meant re-wrapping it after streaming.

    ``aiter_bytes()`` yields decoded bytes, so carrying the original
    ``Content-Encoding: gzip`` header over made httpx decompress the body a
    second time and fail with "incorrect header check". Both providers gzip
    their responses in production, so this broke every live search while the
    mocked tests stayed green.
    """
    import gzip
    import json as json_module

    body = gzip.compress(json_module.dumps(PEXELS_SEARCH).encode())
    transport = RecordingTransport(
        lambda _: httpx.Response(
            200,
            content=body,
            headers={
                "Content-Type": "application/json",
                "Content-Encoding": "gzip",
            },
        )
    )

    async with PexelsProvider("k", transport=transport) as provider:
        results = await provider.search("trees")

    assert len(results) == 1
    assert results[0].id == "pexels_67762"

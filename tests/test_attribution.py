"""Tests for licence-mandated attribution strings.

These are compliance requirements, not formatting preferences: both providers
make correct attribution a condition of API access.
"""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import parse_qs, urlparse

from stocky_mcp.attribution import add_utm, attribution_for
from stocky_mcp.models import ImageResult


def hrefs(html: str) -> list[str]:
    """Extract href targets, so tests assert on links not raw text.

    Values are unescaped: an href legitimately carries ``&amp;`` in markup,
    which would otherwise break query-string parsing.
    """
    return [unescape(href) for href in re.findall(r'href="([^"]+)"', html)]


def make_result(provider: str, **overrides: object) -> ImageResult:
    defaults: dict[str, object] = {
        "id": f"{provider}_123",
        "title": "A photo",
        "description": None,
        "url": "https://img.example/x.jpg",
        "thumbnail": "https://img.example/t.jpg",
        "width": 100,
        "height": 100,
        "photographer": "Emma K",
        "photographer_url": f"https://{provider}.com/@emmak",
        "source": provider.title(),
        "license": "free",
        "attribution_url": f"https://{provider}.com/photos/123",
    }
    defaults.update(overrides)
    return ImageResult(**defaults)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# UTM handling
# --------------------------------------------------------------------------


def test_add_utm_appends_required_parameters() -> None:
    query = parse_qs(urlparse(add_utm("https://unsplash.com/@emmak")).query)

    assert query["utm_source"] == ["stocky-mcp"]
    assert query["utm_medium"] == ["referral"]


def test_add_utm_preserves_an_existing_query() -> None:
    """Unsplash URLs carry an ixid that must survive."""
    query = parse_qs(urlparse(add_utm("https://unsplash.com/photos/x?ixid=abc123")).query)

    assert query["ixid"] == ["abc123"]
    assert query["utm_medium"] == ["referral"]


def test_add_utm_uses_the_supplied_app_name() -> None:
    url = add_utm("https://unsplash.com/", "my-app")

    assert parse_qs(urlparse(url).query)["utm_source"] == ["my-app"]


def test_add_utm_ignores_an_empty_url() -> None:
    assert add_utm("") == ""


# --------------------------------------------------------------------------
# Unsplash
# --------------------------------------------------------------------------


def test_unsplash_credits_photographer_and_unsplash() -> None:
    """Unsplash requires crediting both the photographer and Unsplash."""
    attribution = attribution_for(make_result("unsplash"))

    assert attribution["text"] == "Photo by Emma K on Unsplash"
    assert "Emma K" in attribution["html"]
    assert "Unsplash</a>" in attribution["html"]


def test_unsplash_links_carry_utm_parameters() -> None:
    attribution = attribution_for(make_result("unsplash"))

    for url in (attribution["photographer_url"], attribution["source_url"]):
        query = parse_qs(urlparse(url).query)
        assert query["utm_source"] == ["stocky-mcp"]
        assert query["utm_medium"] == ["referral"]

    # Both links in the markup must carry the parameters, not just one.
    assert len(hrefs(attribution["html"])) == 2
    for href in hrefs(attribution["html"]):
        assert parse_qs(urlparse(href).query)["utm_medium"] == ["referral"]


def test_unsplash_handles_a_missing_photographer_url() -> None:
    attribution = attribution_for(make_result("unsplash", photographer_url=None))

    assert attribution["text"] == "Photo by Emma K on Unsplash"


# --------------------------------------------------------------------------
# Pexels
# --------------------------------------------------------------------------


def test_pexels_links_back_to_pexels_and_the_photo() -> None:
    attribution = attribution_for(make_result("pexels"))

    assert attribution["text"] == "Photo by Emma K on Pexels"
    # Assert the exact links. Substring checks against a URL are unreliable
    # (and CodeQL rightly flags them): "www.pexels.com" appearing somewhere
    # in the markup would not prove it is the href of a real link.
    assert hrefs(attribution["html"]) == [
        "https://pexels.com/photos/123",
        "https://pexels.com/@emmak",
        "https://www.pexels.com",
    ]


def test_pexels_does_not_add_utm_parameters() -> None:
    """UTM tagging is an Unsplash requirement; Pexels does not ask for it."""
    attribution = attribution_for(make_result("pexels"))

    assert "utm_source" not in attribution["html"]


def test_pexels_falls_back_when_urls_are_missing() -> None:
    attribution = attribution_for(
        make_result("pexels", attribution_url=None, photographer_url=None)
    )

    assert attribution["photographer_url"] == "https://www.pexels.com"
    assert attribution["source_url"] == "https://www.pexels.com"

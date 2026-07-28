"""Tests for licence-mandated attribution strings.

These are compliance requirements, not formatting preferences: both providers
make correct attribution a condition of API access.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from stocky_mcp.attribution import add_utm, attribution_for
from stocky_mcp.models import ImageResult


def hrefs(html: str) -> list[str]:
    """Extract href targets, so tests assert on links not raw text."""
    return re.findall(r'href="([^"]+)"', html)


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
    result = add_utm("https://unsplash.com/@emmak")

    assert "utm_source=stocky-mcp" in result
    assert "utm_medium=referral" in result


def test_add_utm_preserves_an_existing_query() -> None:
    """Unsplash URLs carry an ixid that must survive."""
    result = add_utm("https://unsplash.com/photos/x?ixid=abc123")

    assert "ixid=abc123" in result
    assert "utm_medium=referral" in result


def test_add_utm_uses_the_supplied_app_name() -> None:
    assert "utm_source=my-app" in add_utm("https://unsplash.com/", "my-app")


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

    assert "utm_source=stocky-mcp" in attribution["photographer_url"]
    assert "utm_source=stocky-mcp" in attribution["source_url"]
    assert attribution["html"].count("utm_medium=referral") == 2


def test_unsplash_handles_a_missing_photographer_url() -> None:
    attribution = attribution_for(make_result("unsplash", photographer_url=None))

    assert attribution["text"] == "Photo by Emma K on Unsplash"


# --------------------------------------------------------------------------
# Pexels
# --------------------------------------------------------------------------


def test_pexels_links_back_to_pexels_and_the_photo() -> None:
    attribution = attribution_for(make_result("pexels"))

    assert attribution["text"] == "Photo by Emma K on Pexels"
    # Compare parsed hosts rather than substrings: "https://www.pexels.com"
    # appearing anywhere in the markup would not prove it is a real href.
    hosts = {urlparse(href).netloc for href in hrefs(attribution["html"])}
    assert "www.pexels.com" in hosts
    assert "https://pexels.com/photos/123" in hrefs(attribution["html"])


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

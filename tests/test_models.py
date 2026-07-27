"""Tests for the ImageResult model."""

from __future__ import annotations

import pytest

from stocky_mcp.models import SIZE_NAMES, ImageResult


def make_result(**overrides: object) -> ImageResult:
    """Build an ImageResult with sensible defaults, overriding as needed."""
    defaults: dict[str, object] = {
        "id": "pexels_123",
        "title": "A mountain",
        "description": "Snowy peak",
        "url": "https://img.example/large.jpg",
        "thumbnail": "https://img.example/thumb.jpg",
        "width": 1920,
        "height": 1080,
        "photographer": "Ada",
        "photographer_url": "https://example.com/ada",
        "source": "Pexels",
        "license": "Free to use",
    }
    defaults.update(overrides)
    return ImageResult(**defaults)  # type: ignore[arg-type]


def test_provider_is_parsed_from_the_id_prefix() -> None:
    assert make_result(id="unsplash_abc").provider == "unsplash"


def test_provider_handles_ids_containing_underscores() -> None:
    """Unsplash ids can contain underscores, so only the first splits."""
    assert make_result(id="unsplash_aB_c-d").provider == "unsplash"


def test_tags_default_to_an_empty_list() -> None:
    assert make_result().tags == []


def test_tags_are_not_shared_between_instances() -> None:
    """A mutable default would leak tags across every result."""
    first, second = make_result(), make_result()
    first.tags.append("mountain")

    assert second.tags == []


def test_none_tags_are_normalised() -> None:
    assert make_result(tags=None).tags == []


def test_none_sizes_are_normalised() -> None:
    assert make_result(sizes=None).sizes == {}


def test_url_for_size_returns_exact_match() -> None:
    result = make_result(
        sizes={"medium": "https://img.example/m.jpg", "large": "https://x/l.jpg"}
    )

    assert result.url_for_size("medium") == "https://img.example/m.jpg"


def test_url_for_size_prefers_a_smaller_size_when_absent() -> None:
    """Falling back downwards avoids handing back a needlessly huge image."""
    result = make_result(
        sizes={"small": "https://img.example/s.jpg", "original": "https://x/o.jpg"}
    )

    assert result.url_for_size("medium") == "https://img.example/s.jpg"


def test_url_for_size_falls_back_upwards_when_nothing_smaller_exists() -> None:
    result = make_result(sizes={"large": "https://img.example/l.jpg"})

    assert result.url_for_size("thumbnail") == "https://img.example/l.jpg"


def test_url_for_size_falls_back_to_url_when_sizes_are_empty() -> None:
    result = make_result(sizes={})

    assert result.url_for_size("large") == "https://img.example/large.jpg"


def test_url_for_size_rejects_an_unknown_size() -> None:
    result = make_result(sizes={"large": "https://img.example/l.jpg"})

    assert result.url_for_size("gigantic") is None


@pytest.mark.parametrize("size", SIZE_NAMES)
def test_url_for_size_always_resolves_when_any_size_exists(size: str) -> None:
    result = make_result(sizes={"medium": "https://img.example/m.jpg"})

    assert result.url_for_size(size) is not None


def test_to_dict_round_trips_all_fields() -> None:
    result = make_result(
        tags=["mountain"],
        sizes={"large": "https://img.example/l.jpg"},
        attribution_url="https://example.com/photo",
    )

    data = result.to_dict()

    assert data["id"] == "pexels_123"
    assert data["tags"] == ["mountain"]
    assert data["sizes"] == {"large": "https://img.example/l.jpg"}
    assert data["attribution_url"] == "https://example.com/photo"


def test_to_dict_is_json_serialisable() -> None:
    import json

    json.dumps(make_result().to_dict())

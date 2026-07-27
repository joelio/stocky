"""Attribution strings required by the provider licences.

Both providers make attribution a condition of API access, and each specifies
a different format. Unsplash additionally requires UTM parameters on every
link back. Generating these correctly is a licensing matter, not cosmetics,
so it lives in one tested place rather than being improvised at each call site.

- Pexels: https://www.pexels.com/api/documentation/ (Guidelines)
- Unsplash: https://help.unsplash.com/en/articles/2511245-unsplash-api-guidelines
"""

from __future__ import annotations

from urllib.parse import urlencode, urlparse, urlunparse

from .models import ImageResult

#: Sent as ``utm_source`` on Unsplash links. Unsplash requires the referring
#: application's name.
DEFAULT_APP_NAME = "stocky-mcp"


def add_utm(url: str, app_name: str = DEFAULT_APP_NAME) -> str:
    """Append Unsplash's required referral parameters to ``url``.

    Existing query parameters are preserved rather than overwritten, because
    Unsplash URLs carry an ``ixid`` that must survive intact.
    """
    if not url:
        return url

    parts = urlparse(url)
    extra = urlencode({"utm_source": app_name, "utm_medium": "referral"})
    query = f"{parts.query}&{extra}" if parts.query else extra
    return urlunparse(parts._replace(query=query))


def attribution_for(
    result: ImageResult,
    app_name: str = DEFAULT_APP_NAME,
) -> dict[str, str]:
    """Build the attribution block for a single result.

    Returns:
        A mapping with ``text`` (plain text), ``html`` (the provider's
        required markup), ``photographer_url`` and ``source_url``. Callers
        should surface at least ``text`` wherever the image is displayed.
    """
    if result.provider == "unsplash":
        return _unsplash_attribution(result, app_name)
    return _pexels_attribution(result)


def _unsplash_attribution(result: ImageResult, app_name: str) -> dict[str, str]:
    """Unsplash requires crediting the photographer *and* Unsplash itself."""
    photographer_url = add_utm(result.photographer_url or "", app_name)
    source_url = add_utm("https://unsplash.com/", app_name)

    return {
        "text": f"Photo by {result.photographer} on Unsplash",
        "html": (
            f'Photo by <a href="{photographer_url}">{result.photographer}</a> '
            f'on <a href="{source_url}">Unsplash</a>'
        ),
        "photographer_url": photographer_url,
        "source_url": source_url,
    }


def _pexels_attribution(result: ImageResult) -> dict[str, str]:
    """Pexels requires a link back to Pexels and, where possible, the author."""
    photo_url = result.attribution_url or "https://www.pexels.com"
    photographer_url = result.photographer_url or "https://www.pexels.com"

    return {
        "text": f"Photo by {result.photographer} on Pexels",
        "html": (
            f'This <a href="{photo_url}">Photo</a> was taken by '
            f'<a href="{photographer_url}">{result.photographer}</a> on '
            f'<a href="https://www.pexels.com">Pexels</a>'
        ),
        "photographer_url": photographer_url,
        "source_url": "https://www.pexels.com",
    }

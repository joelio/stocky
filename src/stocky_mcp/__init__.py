"""Stocky — an MCP server for royalty-free stock image search.

The names re-exported here are the supported public surface. Everything else
is an implementation detail and may change without a major version bump.
"""

from .attribution import attribution_for
from .cache import TTLCache
from .config import Config, configure_logging
from .errors import (
    ConfigurationError,
    ProviderAuthError,
    ProviderError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    StockyError,
)
from .manager import StockImageManager
from .models import SIZE_NAMES, ImageResult
from .providers.base import StockImageProvider
from .providers.pexels import PexelsProvider
from .providers.unsplash import UnsplashProvider

__version__ = "2.0.0"

__all__ = [
    "SIZE_NAMES",
    "Config",
    "ConfigurationError",
    "ImageResult",
    "PexelsProvider",
    "ProviderAuthError",
    "ProviderError",
    "ProviderNotFoundError",
    "ProviderRateLimitError",
    "ProviderTimeoutError",
    "StockImageManager",
    "StockImageProvider",
    "StockyError",
    "TTLCache",
    "UnsplashProvider",
    "__version__",
    "attribution_for",
    "configure_logging",
]


def __getattr__(name: str) -> object:
    """Import the server lazily.

    ``server`` pulls in the ``mcp`` package, which is slow and unnecessary for
    callers that only want the providers or models.
    """
    if name not in {"server", "StockyServer", "build_server", "main"}:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    # importlib rather than `from . import server`: the latter re-enters this
    # function through the import machinery's attribute lookup and recurses.
    import importlib

    module = importlib.import_module(f"{__name__}.server")
    globals()["server"] = module

    return module if name == "server" else getattr(module, name)

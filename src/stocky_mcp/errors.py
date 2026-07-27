"""Typed errors raised by stock image providers.

The previous implementation swallowed every failure and returned an empty
result list, which made an authentication failure indistinguishable from a
search that genuinely matched nothing. These types let the manager report
what actually went wrong, per provider.
"""

from __future__ import annotations


class StockyError(Exception):
    """Base class for all Stocky errors."""


class ConfigurationError(StockyError):
    """Raised when the server is misconfigured, e.g. a missing API key."""


class ProviderError(StockyError):
    """A provider request failed.

    Attributes:
        provider: Name of the provider that failed, e.g. ``"pexels"``.
        status_code: HTTP status code, when the failure was an HTTP response.
    """

    def __init__(
        self,
        provider: str,
        message: str,
        status_code: int | None = None,
    ) -> None:
        self.provider = provider
        self.status_code = status_code
        super().__init__(message)


class ProviderAuthError(ProviderError):
    """The provider rejected our credentials (HTTP 401/403)."""


class ProviderRateLimitError(ProviderError):
    """The provider rate limit was exceeded (HTTP 429)."""


class ProviderNotFoundError(ProviderError):
    """The requested image does not exist (HTTP 404)."""


class ProviderTimeoutError(ProviderError):
    """The provider did not respond within the configured timeout."""

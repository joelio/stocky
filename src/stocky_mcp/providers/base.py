"""Shared behaviour for stock image providers."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Mapping
from types import TracebackType
from typing import Any, TypeVar

import httpx

from ..errors import (
    ProviderAuthError,
    ProviderError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from ..models import ImageResult

logger = logging.getLogger(__name__)

#: Lets __aenter__ return the concrete subclass rather than the base type.
#: typing.Self would be tidier but only exists from Python 3.11, and this
#: package supports 3.10 without taking a typing_extensions dependency.
ProviderT = TypeVar("ProviderT", bound="StockImageProvider")


class StockImageProvider(ABC):
    """Base class for a stock image provider backed by an HTTP API.

    Providers are async context managers. The HTTP client is created on entry
    and closed on exit, so connections are pooled for the lifetime of a call
    and never leaked:

        async with PexelsProvider(key) as provider:
            results = await provider.search("mountains")

    Subclasses implement :meth:`search` and :meth:`get_details`, and use
    :meth:`request_json` for transport, which centralises timeout handling and
    the mapping from HTTP status codes to typed errors.
    """

    #: Provider key used in image id prefixes, e.g. ``"pexels"``.
    name: str = ""
    #: Root URL for the provider API.
    base_url: str = ""

    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 15.0,
        user_agent: str = "stocky-mcp",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Initialise the provider.

        Args:
            api_key: Credential for the provider API.
            timeout: Per-request timeout in seconds.
            user_agent: User-Agent header value.
            transport: Optional transport override. Tests pass an
                ``httpx.MockTransport`` here to avoid network access.
        """
        if not api_key:
            raise ValueError(self.missing_key_message())
        self.api_key = api_key
        self.timeout = timeout
        self.user_agent = user_agent
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    @classmethod
    def missing_key_message(cls) -> str:
        """Human-readable guidance for a missing credential."""
        return f"{cls.name or cls.__name__} API key is missing."

    def auth_headers(self) -> dict[str, str]:
        """Provider-specific authentication headers."""
        raise NotImplementedError

    def _headers(self) -> dict[str, str]:
        # Pexels' edge returns 403 for requests without a User-Agent, so this
        # is set for every provider rather than relying on httpx's default.
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        headers.update(self.auth_headers())
        return headers

    async def __aenter__(self: ProviderT) -> ProviderT:  # noqa: PYI019
        """Open the HTTP client."""
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._headers(),
            timeout=self.timeout,
            transport=self._transport,
            follow_redirects=True,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        """The active HTTP client.

        Raises:
            RuntimeError: If accessed outside the async context manager.
        """
        if self._client is None:
            raise RuntimeError(
                f"{type(self).__name__} must be used as an async context "
                f"manager: 'async with {type(self).__name__}(key) as p:'"
            )
        return self._client

    async def request_json(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """GET ``path`` and return the decoded JSON body.

        Raises:
            ProviderAuthError: On 401/403.
            ProviderRateLimitError: On 429.
            ProviderNotFoundError: On 404.
            ProviderTimeoutError: If the request timed out.
            ProviderError: On any other transport or decoding failure.
        """
        # Drop unset optional parameters so we never send "param=None".
        clean_params = (
            {k: v for k, v in params.items() if v is not None} if params else None
        )

        try:
            response = await self.client.get(path, params=clean_params)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                self.name, f"{self.name} request timed out after {self.timeout}s"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(self.name, f"{self.name} request failed: {exc}") from exc

        self._raise_for_status(response)

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(
                self.name, f"{self.name} returned a malformed JSON response"
            ) from exc

        if not isinstance(data, dict):
            raise ProviderError(
                self.name,
                f"{self.name} returned unexpected JSON of type {type(data).__name__}",
            )
        return data

    def is_rate_limited(self, response: httpx.Response) -> bool:
        """Whether ``response`` represents a rate-limit rejection.

        Overridable because providers disagree: Pexels returns 429, while
        Unsplash returns 403 with ``X-Ratelimit-Remaining: 0``.
        """
        return response.status_code == 429

    def _raise_for_status(self, response: httpx.Response) -> None:
        """Translate an error status code into a typed provider error."""
        status = response.status_code
        if status < 400:
            return

        detail = self._error_detail(response)

        # Checked before the auth branch, since a provider may signal a rate
        # limit with a status code that otherwise means "forbidden".
        if self.is_rate_limited(response):
            raise ProviderRateLimitError(
                self.name,
                f"{self.name} rate limit exceeded (HTTP {status}). {detail}".strip(),
                status_code=status,
            )

        if status in (401, 403):
            raise ProviderAuthError(
                self.name,
                f"{self.name} rejected the API key (HTTP {status}). "
                f"Check the credential is set and valid. {detail}".strip(),
                status_code=status,
            )
        if status == 404:
            raise ProviderNotFoundError(
                self.name,
                f"{self.name} has no such image (HTTP 404). {detail}".strip(),
                status_code=status,
            )
        raise ProviderError(
            self.name,
            f"{self.name} returned HTTP {status}. {detail}".strip(),
            status_code=status,
        )

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        """Best-effort extraction of a provider's error message."""
        try:
            body = response.json()
        except ValueError:
            return ""
        if isinstance(body, dict):
            for key in ("error", "message", "errors", "detail"):
                if key in body:
                    value = body[key]
                    if isinstance(value, list):
                        return "; ".join(str(item) for item in value)
                    return str(value)
        return ""

    @abstractmethod
    async def search(
        self,
        query: str,
        per_page: int = 20,
        page: int = 1,
        **kwargs: Any,
    ) -> list[ImageResult]:
        """Search the provider for images matching ``query``."""

    @abstractmethod
    async def get_details(self, image_id: str) -> ImageResult | None:
        """Fetch a single image by its provider-native id."""

    def strip_prefix(self, image_id: str) -> str:
        """Remove our ``<provider>_`` prefix from an id, if present."""
        prefix = f"{self.name}_"
        return image_id.removeprefix(prefix)

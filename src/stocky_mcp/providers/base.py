"""Shared behaviour for stock image providers."""

from __future__ import annotations

import logging
import re
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

#: Ceiling on a JSON response body. Provider search responses are a few
#: hundred kilobytes at most, so this is generous; it exists to bound memory
#: if a response is hostile or corrupted.
MAX_JSON_BYTES = 8 * 1024 * 1024

#: Provider-native ids are opaque, but they are interpolated into a URL path,
#: so they are constrained rather than trusted. This blocks "../" traversal
#: onto other authenticated endpoints and query-parameter injection.
SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


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
        max_json_bytes: int = MAX_JSON_BYTES,
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
        self.max_json_bytes = max_json_bytes
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
            max_redirects=5,
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
            response = await self._get_capped(path, clean_params)
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

    async def _get_capped(
        self,
        path: str,
        params: dict[str, Any] | None,
    ) -> httpx.Response:
        """GET ``path``, refusing to buffer more than the JSON size cap.

        A plain ``client.get`` reads the whole body into memory with no limit,
        and httpx advertises gzip, so a small compressed response can decode
        into gigabytes. Streaming with a running total bounds that, whatever
        the ``Content-Length`` header claims.
        """
        chunks: list[bytes] = []
        total = 0

        async with self.client.stream("GET", path, params=params) as response:
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > self.max_json_bytes:
                    raise ProviderError(
                        self.name,
                        f"{self.name} response exceeded the "
                        f"{self.max_json_bytes} byte limit",
                    )
                chunks.append(chunk)

            # Re-wrap as a normal response so callers keep .json()/.headers.
            # aiter_bytes() yields *decoded* bytes, so the transfer-encoding
            # headers must not be carried over — httpx would otherwise try to
            # decompress the already-decompressed body and fail with
            # "incorrect header check".
            headers = httpx.Headers(
                [
                    (key, value)
                    for key, value in response.headers.multi_items()
                    if key.lower() not in ("content-encoding", "content-length")
                ]
            )
            return httpx.Response(
                status_code=response.status_code,
                headers=headers,
                content=b"".join(chunks),
                request=response.request,
            )

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

    def _error_detail(self, response: httpx.Response) -> str:
        """Best-effort extraction of a provider's error message.

        The result is returned to the caller and logged, so it is truncated
        and has the API key stripped: some APIs echo the rejected credential
        back in their error body.
        """
        try:
            body = response.json()
        except ValueError:
            return ""

        detail = ""
        if isinstance(body, dict):
            for key in ("error", "message", "errors", "detail"):
                if key in body:
                    value = body[key]
                    detail = (
                        "; ".join(str(item) for item in value)
                        if isinstance(value, list)
                        else str(value)
                    )
                    break

        return self._redact(detail)

    def _redact(self, text: str, limit: int = 200) -> str:
        """Remove the API key from ``text`` and truncate it."""
        if self.api_key and self.api_key in text:
            text = text.replace(self.api_key, "***redacted***")
        return text if len(text) <= limit else text[:limit] + "..."

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
        """Remove our ``<provider>_`` prefix and validate what remains.

        Raises:
            ProviderError: If the id is not a plausible provider id. It is
                interpolated into a URL path and httpx normalises dot
                segments, so an unchecked value could reach a different
                endpoint on the provider's own API using the caller's key.
        """
        native = image_id.removeprefix(f"{self.name}_")

        if not SAFE_ID.match(native):
            raise ProviderError(
                self.name,
                f"Invalid {self.name} image id: expected letters, digits, "
                f"'.', '_' or '-'.",
            )
        return native

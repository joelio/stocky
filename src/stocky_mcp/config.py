"""Environment-driven configuration.

MCP clients launch the server as a subprocess and pass configuration through
environment variables, so that is the only configuration source. Parsing is
collected here rather than scattered through the modules, so the full surface
is documented in one place and is trivial to construct in tests.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Mapping

logger = logging.getLogger(__name__)

DEFAULT_CACHE_TTL = 300.0
DEFAULT_HTTP_TIMEOUT = 15.0
DEFAULT_MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024  # 25 MiB
DEFAULT_USER_AGENT = "stocky-mcp"

_TRUTHY = {"1", "true", "yes", "on"}
_FALSEY = {"0", "false", "no", "off", ""}


def _get_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    """Read a boolean env var, warning (not failing) on an unparseable value."""
    raw = env.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUTHY:
        return True
    if value in _FALSEY:
        return False
    logger.warning(
        "Ignoring invalid boolean for %s: %r (expected true/false)", name, raw
    )
    return default


def _get_number(
    env: Mapping[str, str],
    name: str,
    default: float,
    minimum: float = 0.0,
) -> float:
    """Read a numeric env var, clamping below ``minimum`` and warning on junk."""
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "Ignoring invalid number for %s: %r (expected a number)", name, raw
        )
        return default
    if value < minimum:
        logger.warning(
            "Value for %s (%s) is below the minimum %s; using the minimum",
            name,
            value,
            minimum,
        )
        return minimum
    return value


@dataclass(frozen=True)
class Config:
    """Resolved server configuration.

    Attributes:
        pexels_api_key: Pexels API key, or ``None`` if the provider is disabled.
        unsplash_access_key: Unsplash access key, or ``None`` if disabled.
        enable_attribution: Whether attribution URLs are included by default.
        cache_ttl: Search cache lifetime in seconds; ``0`` disables caching.
        http_timeout: Per-request timeout in seconds for provider calls.
        max_download_bytes: Refuse downloads larger than this, to avoid
            pulling an unbounded response into memory.
        log_level: Logging level name applied to the ``stocky_mcp`` logger.
        user_agent: User-Agent sent to providers. Pexels' edge rejects
            requests without one.
    """

    pexels_api_key: str | None = None
    unsplash_access_key: str | None = None
    enable_attribution: bool = False
    cache_ttl: float = DEFAULT_CACHE_TTL
    http_timeout: float = DEFAULT_HTTP_TIMEOUT
    max_download_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES
    log_level: str = "INFO"
    user_agent: str = DEFAULT_USER_AGENT
    allow_absolute_download_paths: bool = True
    download_root: str | None = field(default=None)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Config":
        """Build a configuration from environment variables."""
        env = os.environ if env is None else env

        def _clean(name: str) -> str | None:
            value = env.get(name, "").strip()
            return value or None

        return cls(
            pexels_api_key=_clean("PEXELS_API_KEY"),
            unsplash_access_key=_clean("UNSPLASH_ACCESS_KEY"),
            enable_attribution=_get_bool(env, "ENABLE_ATTRIBUTION_LINKS", False),
            cache_ttl=_get_number(env, "STOCKY_CACHE_TTL", DEFAULT_CACHE_TTL),
            http_timeout=_get_number(
                env, "STOCKY_HTTP_TIMEOUT", DEFAULT_HTTP_TIMEOUT, minimum=0.1
            ),
            max_download_bytes=int(
                _get_number(
                    env,
                    "STOCKY_MAX_DOWNLOAD_BYTES",
                    DEFAULT_MAX_DOWNLOAD_BYTES,
                    minimum=1,
                )
            ),
            log_level=(env.get("STOCKY_LOG_LEVEL") or "INFO").strip().upper(),
            user_agent=(env.get("STOCKY_USER_AGENT") or DEFAULT_USER_AGENT).strip(),
            download_root=_clean("STOCKY_DOWNLOAD_ROOT"),
        )

    @property
    def configured_providers(self) -> list[str]:
        """Names of providers that have credentials available."""
        providers = []
        if self.pexels_api_key:
            providers.append("pexels")
        if self.unsplash_access_key:
            providers.append("unsplash")
        return providers


def configure_logging(config: Config) -> None:
    """Send logs to stderr at the configured level.

    This must never write to stdout. The stdio transport uses stdout for
    JSON-RPC frames, and anything else written there corrupts the stream and
    makes clients hang on ``initialize`` rather than report a clean error.
    """
    level = getattr(logging, config.log_level, None)
    if not isinstance(level, int):
        level = logging.INFO

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )

    package_logger = logging.getLogger("stocky_mcp")
    package_logger.handlers.clear()
    package_logger.addHandler(handler)
    package_logger.setLevel(level)
    # Don't propagate to the root logger, which may have a stdout handler
    # installed by an embedding application.
    package_logger.propagate = False

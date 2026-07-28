"""Tests for environment-driven configuration."""

from __future__ import annotations

import dataclasses
import logging
import sys

import pytest

from stocky_mcp.config import (
    DEFAULT_CACHE_TTL,
    DEFAULT_HTTP_TIMEOUT,
    DEFAULT_MAX_DOWNLOAD_BYTES,
    Config,
    configure_logging,
)


def test_empty_environment_yields_defaults() -> None:
    config = Config.from_env({})

    assert config.pexels_api_key is None
    assert config.unsplash_access_key is None
    assert config.enable_attribution is False
    assert config.cache_ttl == DEFAULT_CACHE_TTL
    assert config.http_timeout == DEFAULT_HTTP_TIMEOUT
    assert config.max_download_bytes == DEFAULT_MAX_DOWNLOAD_BYTES
    assert config.log_level == "INFO"
    assert config.configured_providers == []


def test_api_keys_are_read_and_stripped() -> None:
    config = Config.from_env({"PEXELS_API_KEY": "  pk  ", "UNSPLASH_ACCESS_KEY": "uk"})

    assert config.pexels_api_key == "pk"
    assert config.unsplash_access_key == "uk"
    assert config.configured_providers == ["pexels", "unsplash"]


def test_whitespace_only_key_is_treated_as_absent() -> None:
    """A client passing an empty env var must not enable a broken provider."""
    config = Config.from_env({"PEXELS_API_KEY": "   "})

    assert config.pexels_api_key is None
    assert config.configured_providers == []


@pytest.mark.parametrize("raw", ["true", "TRUE", "True", "1", "yes", "on"])
def test_truthy_boolean_values(raw: str) -> None:
    assert Config.from_env({"ENABLE_ATTRIBUTION_LINKS": raw}).enable_attribution


@pytest.mark.parametrize("raw", ["false", "FALSE", "0", "no", "off", ""])
def test_falsey_boolean_values(raw: str) -> None:
    config = Config.from_env({"ENABLE_ATTRIBUTION_LINKS": raw})
    assert config.enable_attribution is False


def test_invalid_boolean_falls_back_to_default(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="stocky_mcp.config"):
        config = Config.from_env({"ENABLE_ATTRIBUTION_LINKS": "maybe"})

    assert config.enable_attribution is False
    assert "invalid boolean" in caplog.text.lower()


def test_cache_ttl_is_parsed() -> None:
    assert Config.from_env({"STOCKY_CACHE_TTL": "90"}).cache_ttl == 90.0


def test_cache_ttl_zero_is_preserved() -> None:
    """Zero is meaningful: it disables caching, so it must not be clamped."""
    assert Config.from_env({"STOCKY_CACHE_TTL": "0"}).cache_ttl == 0.0


def test_negative_cache_ttl_is_clamped_to_zero(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="stocky_mcp.config"):
        config = Config.from_env({"STOCKY_CACHE_TTL": "-30"})

    assert config.cache_ttl == 0.0
    assert "below the minimum" in caplog.text


def test_invalid_number_falls_back_to_default(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="stocky_mcp.config"):
        config = Config.from_env({"STOCKY_CACHE_TTL": "soon"})

    assert config.cache_ttl == DEFAULT_CACHE_TTL
    assert "invalid number" in caplog.text.lower()


def test_http_timeout_has_a_nonzero_floor() -> None:
    """A zero timeout would mean 'fail instantly', which is never intended."""
    assert Config.from_env({"STOCKY_HTTP_TIMEOUT": "0"}).http_timeout == 0.1


def test_max_download_bytes_is_an_int() -> None:
    config = Config.from_env({"STOCKY_MAX_DOWNLOAD_BYTES": "1048576"})

    assert config.max_download_bytes == 1048576
    assert isinstance(config.max_download_bytes, int)


def test_log_level_is_upper_cased() -> None:
    assert Config.from_env({"STOCKY_LOG_LEVEL": "debug"}).log_level == "DEBUG"


def test_configured_providers_lists_only_credentialled_ones() -> None:
    config = Config.from_env({"UNSPLASH_ACCESS_KEY": "uk"})

    assert config.configured_providers == ["unsplash"]


def test_config_is_immutable() -> None:
    config = Config.from_env({})

    with pytest.raises(dataclasses.FrozenInstanceError):
        config.cache_ttl = 10  # type: ignore[misc]


def test_configure_logging_never_writes_to_stdout() -> None:
    """stdout carries JSON-RPC frames; a log line there breaks the protocol."""
    configure_logging(Config.from_env({"STOCKY_LOG_LEVEL": "DEBUG"}))

    package_logger = logging.getLogger("stocky_mcp")
    streams = [
        handler.stream
        for handler in package_logger.handlers
        if isinstance(handler, logging.StreamHandler)
    ]

    assert streams, "expected a stream handler to be installed"
    assert all(stream is sys.stderr for stream in streams)
    assert package_logger.propagate is False


def test_configure_logging_applies_the_level() -> None:
    configure_logging(Config.from_env({"STOCKY_LOG_LEVEL": "WARNING"}))

    assert logging.getLogger("stocky_mcp").level == logging.WARNING


def test_configure_logging_falls_back_on_unknown_level() -> None:
    configure_logging(Config.from_env({"STOCKY_LOG_LEVEL": "LOUD"}))

    assert logging.getLogger("stocky_mcp").level == logging.INFO


def test_configure_logging_is_idempotent() -> None:
    """Repeated calls must not stack duplicate handlers and double every line."""
    config = Config.from_env({})
    configure_logging(config)
    configure_logging(config)

    assert len(logging.getLogger("stocky_mcp").handlers) == 1

"""Tests for the package's public surface and console entry point."""

from __future__ import annotations

import logging
from typing import Any

import pytest

import stocky_mcp
from stocky_mcp import server as server_module
from stocky_mcp.config import Config

# --------------------------------------------------------------------------
# Public surface
# --------------------------------------------------------------------------


def test_version_is_exported() -> None:
    assert stocky_mcp.__version__


def test_all_exports_actually_exist() -> None:
    """A stale __all__ entry breaks `from stocky_mcp import *` silently."""
    for name in stocky_mcp.__all__:
        assert hasattr(stocky_mcp, name), f"{name} is in __all__ but missing"


def test_server_submodule_is_lazily_available() -> None:
    assert stocky_mcp.server.__name__ == "stocky_mcp.server"


@pytest.mark.parametrize("name", ["StockyServer", "build_server", "main"])
def test_server_names_are_lazily_available(name: str) -> None:
    """These live in `server`, which is only imported on demand."""
    assert hasattr(stocky_mcp, name)


def test_unknown_attribute_raises_attribute_error() -> None:
    with pytest.raises(AttributeError, match="no attribute 'nope'"):
        _ = stocky_mcp.nope  # type: ignore[attr-defined]


def test_providers_are_registered_for_every_known_name() -> None:
    from stocky_mcp.manager import PROVIDER_CLASSES

    assert set(PROVIDER_CLASSES) == {"pexels", "unsplash"}
    for name, cls in PROVIDER_CLASSES.items():
        assert cls.name == name
        assert cls.base_url.startswith("https://")


# --------------------------------------------------------------------------
# main()
# --------------------------------------------------------------------------


@pytest.fixture
def captured_run(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Stop main() short of actually serving, recording the server it built."""
    built: list[Any] = []

    def fake_run(self: Any) -> None:
        built.append(self)

    monkeypatch.setattr(server_module.StockyServer, "run", fake_run)
    return built


def test_main_builds_and_runs_a_server(
    monkeypatch: pytest.MonkeyPatch, captured_run: list[Any]
) -> None:
    monkeypatch.setenv("PEXELS_API_KEY", "pk")

    server_module.main()

    assert len(captured_run) == 1
    assert captured_run[0].manager.available_providers == ["pexels"]


class ListHandler(logging.Handler):
    """Collects records straight off a logger.

    ``caplog`` attaches to the root logger, which never sees these records:
    ``configure_logging`` sets ``propagate = False`` so that an embedding
    application's stdout handler cannot corrupt the JSON-RPC stream.
    """

    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def test_main_starts_without_credentials_but_warns(
    monkeypatch: pytest.MonkeyPatch,
    captured_run: list[Any],
) -> None:
    """Exiting here would surface in clients as an unexplained handshake hang."""
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.delenv("UNSPLASH_ACCESS_KEY", raising=False)

    handler = ListHandler()
    logging.getLogger("stocky_mcp.server").addHandler(handler)
    try:
        server_module.main()
    finally:
        logging.getLogger("stocky_mcp.server").removeHandler(handler)

    assert len(captured_run) == 1
    assert any("No provider API keys found" in m for m in handler.messages)


def test_package_logger_does_not_propagate_to_root(
    monkeypatch: pytest.MonkeyPatch, captured_run: list[Any]
) -> None:
    """Propagation to root could route logs to a stdout handler and corrupt
    the JSON-RPC stream, so main() must switch it off."""
    monkeypatch.setenv("PEXELS_API_KEY", "pk")

    server_module.main()

    assert logging.getLogger("stocky_mcp").propagate is False


def test_main_configures_logging_to_stderr(
    monkeypatch: pytest.MonkeyPatch, captured_run: list[Any]
) -> None:
    import sys

    monkeypatch.setenv("PEXELS_API_KEY", "pk")

    server_module.main()

    handlers = logging.getLogger("stocky_mcp").handlers
    assert handlers
    assert all(h.stream is sys.stderr for h in handlers)  # type: ignore[attr-defined]


def test_build_server_defaults_to_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PEXELS_API_KEY", "from-env")

    server = server_module.build_server()

    assert server.config.pexels_api_key == "from-env"


def test_build_server_accepts_an_explicit_config() -> None:
    server = server_module.build_server(Config(unsplash_access_key="uk"))

    assert server.manager.available_providers == ["unsplash"]


def test_help_resource_documents_every_tool() -> None:
    """The help text is the main discovery surface, so it must stay in sync."""
    for tool in ("search_stock_images", "get_image_details", "download_image"):
        assert tool in server_module.HELP_RESOURCE

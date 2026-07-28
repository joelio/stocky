"""Tests for the root ``stocky_mcp.py`` compatibility launcher.

Existing MCP client configurations invoke that file by path. It sits in the
directory Python puts on ``sys.path`` when running a script, so it shadows the
real package by name — these tests guard the workaround that resolves it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SHIM = REPO_ROOT / "stocky_mcp.py"

INITIALIZE = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    }
)


def handshake(*command: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a server command and feed it a single initialize request."""
    return subprocess.run(
        command,
        input=INITIALIZE + "\n",
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        cwd=cwd,
        env={
            "PATH": "/usr/bin:/bin",
            "PEXELS_API_KEY": "test-key",
            "HOME": str(cwd),
        },
    )


def assert_clean_handshake(result: subprocess.CompletedProcess[str]) -> None:
    """Assert stdout carried exactly one valid JSON-RPC response."""
    assert result.stdout, f"no stdout. stderr was:\n{result.stderr}"

    first_line = result.stdout.splitlines()[0]
    # A single stray byte on stdout corrupts the frame and makes clients hang
    # on initialize rather than report an error.
    payload = json.loads(first_line)

    assert payload["id"] == 1
    assert payload["result"]["serverInfo"]["name"] == "stocky"
    assert "jsonrpc" not in result.stderr


@pytest.mark.parametrize("cwd", [REPO_ROOT, Path("/tmp")], ids=["repo-root", "elsewhere"])
def test_shim_completes_a_handshake_from_any_directory(cwd: Path) -> None:
    """The shim must work regardless of the client's working directory."""
    assert_clean_handshake(handshake(sys.executable, str(SHIM), cwd=cwd))


def test_module_invocation_completes_a_handshake() -> None:
    assert_clean_handshake(
        handshake(sys.executable, "-m", "stocky_mcp", cwd=Path("/tmp"))
    )


def test_stdout_carries_no_log_output() -> None:
    """Logging must go to stderr; stdout is reserved for JSON-RPC."""
    result = handshake(sys.executable, str(SHIM), cwd=REPO_ROOT)

    for line in result.stdout.splitlines():
        assert line.startswith("{"), f"non-JSON line on stdout: {line!r}"


def test_startup_logs_go_to_stderr() -> None:
    result = handshake(sys.executable, str(SHIM), cwd=REPO_ROOT)

    assert "Starting Stocky MCP server" in result.stderr


def test_shim_exposes_a_main_callable() -> None:
    """Anything importing the shim for its main() keeps working."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import importlib.util,sys;"
                f"spec=importlib.util.spec_from_file_location('shim', r'{SHIM}');"
                "m=importlib.util.module_from_spec(spec);"
                "spec.loader.exec_module(m);"
                "print(callable(m.main))"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        cwd=str(Path("/tmp")),
    )

    assert result.stdout.strip() == "True", result.stderr

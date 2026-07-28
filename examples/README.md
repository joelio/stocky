# Example MCP client configuration

[`mcp_config_example.json`](mcp_config_example.json) is a ready-to-copy client
configuration. It contains exactly one server, so pasting it registers one
server — keys prefixed with an underscore would still be treated as real
entries, and a client would try to launch them.

The alternatives below are the same server started a different way. Use one.

## Recommended — `uvx`, nothing installed

This is what `mcp_config_example.json` contains.

```json
{
  "mcpServers": {
    "stocky": {
      "command": "uvx",
      "args": ["stocky-mcp"],
      "env": { "PEXELS_API_KEY": "..." }
    }
  }
}
```

## Installed as a tool

```bash
uv tool install stocky-mcp     # or: pipx install stocky-mcp
```

```json
{
  "mcpServers": {
    "stocky": {
      "command": "stocky-mcp",
      "env": { "PEXELS_API_KEY": "..." }
    }
  }
}
```

## From a source checkout

Supported so that existing configurations keep working. Prefer an **absolute
interpreter path**: GUI-launched clients often start with a minimal `PATH` and
cannot find a virtualenv's `python`, which surfaces as a startup timeout rather
than a useful error.

```json
{
  "mcpServers": {
    "stocky": {
      "command": "/path/to/stocky/.venv/bin/python",
      "args": ["/path/to/stocky/stocky_mcp.py"],
      "env": { "PEXELS_API_KEY": "..." }
    }
  }
}
```

## Environment variables

See the configuration table in the [main README](../README.md#configuration).
`STOCKY_DOWNLOAD_ROOT` is worth setting — download paths come from
model-generated tool calls, and it confines writes to one directory.

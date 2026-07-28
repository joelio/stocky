# Contributing to Stocky

Thanks for taking the time. This document covers getting set up, the checks
that must pass, and a few things about this codebase that are easy to trip over.

## Setup

Stocky uses [uv](https://docs.astral.sh/uv/). Install it, then:

```bash
git clone https://github.com/joelio/stocky.git
cd stocky
uv sync --group dev
```

Plain pip works too, with pip 25.1 or newer:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e . --group dev
```

## The checks

CI runs exactly these, so run them before opening a PR:

```bash
uv run pytest -m "not integration"                 # unit tests
uv run ruff check .                                # lint
uv run ruff format --check .                       # formatting
uv run mypy                                        # types
```

Coverage is enforced at 85%. The suite currently sits around 95%, so a drop
usually means new code arrived without tests rather than that the floor is
too high.

### Integration tests

Tests marked `integration` call the real Pexels and Unsplash APIs. They skip
automatically without credentials and never run in CI:

```bash
export PEXELS_API_KEY=... UNSPLASH_ACCESS_KEY=...
uv run pytest -m integration
```

Run them when you change provider request-building or response-parsing. Mocked
tests confirm we send what we intended; only these confirm the providers agree.

## Layout

```
src/stocky_mcp/
  config.py       env-var parsing, logging setup
  models.py       ImageResult
  cache.py        TTLCache for search results
  errors.py       typed provider errors
  attribution.py  licence-required attribution strings
  manager.py      fans out across providers, caching, downloads
  server.py       FastMCP tool and resource registration
  providers/      base.py, pexels.py, unsplash.py
stocky_mcp.py     compatibility launcher (see below)
```

## Things that will catch you out

**Never write to stdout.** The stdio transport carries JSON-RPC on stdout, so a
stray `print()` corrupts the stream and clients hang on `initialize` instead of
reporting an error. Use `logging`, which is pinned to stderr. Ruff's `T20` rule
enforces this.

**The root `stocky_mcp.py` shadows the package.** It exists so that existing
client configurations pointing at the file keep working. Because it sits in the
directory Python adds to `sys.path`, `import stocky_mcp` from the repo root can
resolve to the shim rather than the package. Tests use
`--import-mode=importlib` to avoid this. If you see
`'stocky_mcp' is not a package`, that is what happened.

**The two providers disagree more than you would expect.** These are real
differences, each with a test guarding it:

| | Pexels | Unsplash |
|---|---|---|
| `per_page` maximum | 80 (clamps) | 30 (**silently falls back to 10** above it) |
| Rate limit status | 429 | **403** with `X-Ratelimit-Remaining: 0` |
| Square orientation | `square` | `squarish` |
| Invalid filter value | ignored, returns 200 | rejected with 400 |
| Invalid API key | **returns 200** | 401 |
| Sorting | not supported | `relevant` / `latest` |
| Download reporting | not required | **required** by their guidelines |

**Attribution is a licensing requirement.** Both providers make it a condition
of API access, and each specifies its own format. If you touch
`attribution.py`, check it against their published guidelines rather than
tidying the strings.

## Adding a provider

1. Subclass `StockImageProvider` in `providers/`, setting `name` and `base_url`.
2. Implement `auth_headers`, `search` and `get_details`. Use `request_json` so
   status-code handling and timeouts stay consistent.
3. Override `is_rate_limited` if the provider doesn't use 429.
4. Map its size variants onto the canonical names in `models.SIZE_NAMES`.
5. Register it in `manager.PROVIDER_CLASSES` and add its key to `Config`.
6. Add an attribution branch in `attribution.py` matching its licence terms.
7. Test it with `httpx.MockTransport`, following the existing provider tests.

## Commits and pull requests

Conventional commit prefixes (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`,
`ci:`, `chore:`), with `!` for breaking changes. Explain *why* in the body —
the diff already shows what.

Keep pull requests focused, and update `CHANGELOG.md` under "Unreleased" for
anything user-visible.

## Releasing

1. Update `__version__` in `src/stocky_mcp/__init__.py`.
2. Move the `CHANGELOG.md` entries under a new version heading.
3. Tag: `git tag v2.0.0 && git push --tags`.

The release workflow builds, verifies, and publishes to PyPI via Trusted
Publishing — no API token is stored. It waits on the protected `pypi`
environment, so a human approves each publish.

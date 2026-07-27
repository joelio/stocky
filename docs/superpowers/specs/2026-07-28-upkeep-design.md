# Stocky MCP Server — Upkeep & Modernisation Design

**Date:** 2026-07-28
**Branch:** `chore/upkeep-2026-07`
**Status:** Approved

## Context

Stocky is an MCP server that searches royalty-free stock images from Pexels and
Unsplash. It was written in mid-2025 and has not had a maintenance pass since.

The local checkout had drifted badly from the remote:

- Local `main` was 22 commits behind `origin/main`. Local SSH key auth was
  broken, so `git fetch` had been silently failing; the remote was reached over
  HTTPS instead.
- Uncommitted work sat on that stale base: a half-finished in-memory cache
  feature plus a mass reindentation, six throwaway `fix_indentation*.py`
  scripts, a `stocky_mcp.py.bak`, and a `test_cache.py`.

All of that work was backed up before being discarded, and the cache feature is
reimplemented cleanly as part of this design.

## Goals

1. Bring the repo back to a maintained state: no stale branches, no junk files,
   issues and PRs triaged against evidence.
2. Fix the real defects found during investigation.
3. Raise test coverage from effectively zero to ~90%, enforced in CI.
4. Modernise packaging, linting, and CI to current practice.
5. Keep existing users working. Do not break anyone's MCP client config.

## Non-goals

- Adding new stock image providers.
- Changing the MCP tool surface (`search_stock_images`, `get_image_details`,
  `download_image`) in any backwards-incompatible way.
- Rewriting the demo or example scripts beyond what the restructure requires.

## Findings

### Issue triage

| Issue | Verdict | Evidence |
|---|---|---|
| #9 "Tests broken" | Already fixed | `test_mcp_client.py` runs clean on current `main`: session initialises, all 3 tools list, tools execute. Fixed by merged PR #12, never auto-closed. |
| #10 "Zed init timeout" | Cannot reproduce; harden underlying causes | A real `initialize` request against current `main` with `mcp` 1.28.1 returns correct capabilities in ~0.3s, both with and without API keys set. |

Issue #10 could not be reproduced, but two genuine defects can produce exactly
the reported symptom and are fixed here:

1. **stdout pollution.** `stocky_mcp.py` prints `"Error: MCP package not
   found"` to **stdout**. The stdio transport uses stdout for JSON-RPC, so this
   corrupts the stream and the client hangs rather than reporting a clean error.
   Fixed by writing to stderr.
2. **Unguarded `import pycurl` before the guarded `mcp` import.** A missing
   pycurl produced a bare traceback and an immediate exit, so the client saw
   EOF with no response — indistinguishable from a hang. Removing pycurl
   entirely removes this failure mode.

A console entry point (`stocky-mcp`) further reduces the risk, since users no
longer have to name an interpreter that may lack the dependencies.

### PR triage

| PR | Action |
|---|---|
| #13 `actions/checkout` 6→7 | Superseded — workflows rewritten with current versions. Close. |
| #17 `actions/setup-python` 6→7 | Superseded — same. Close. |
| #15 `mcp` >=1.28.1 | Adopt the floor in `pyproject.toml`. Close. |
| #16 `pycurl` >=7.47.0 | Obsolete — dependency removed. Close. |

### Defects found by reading the code

- **Blocking I/O in async functions.** Every provider method is `async def` but
  calls `pycurl.Curl().perform()`, which blocks the event loop for the whole
  request. Concurrency was illusory.
- **curl handle leak.** `c.close()` is called *after* the non-200 early return,
  so every failed request leaks a handle.
- **Inconsistent attribution.** `PexelsProvider.search` never sets
  `attribution_url`, while `get_details` does.
- **Lossy size handling.** `ImageResult` keeps only `url` and `thumbnail`,
  discarding the other size variants both APIs return. `download_image` then
  reconstructs "original" for Pexels with a literal string hack —
  `url.replace("?h=650&w=940", "")` — instead of using `src.original`.
- **Unbounded download.** `download_image` reads an arbitrary remote response
  fully into memory and may base64 it into the MCP response, with no size cap.
- **Unvalidated output path.** `output_path` is written to without validation.
- **`StockyServer.run` is broken.** `async def run(self): await self.mcp.run()`
  awaits a non-awaitable. Unused in practice, since `main()` calls
  `self.mcp.run()` directly, but it is wrong and is removed.
- **Dead code.** In `get_image_details`, a prefix-matching loop assigns
  `provider_name` without breaking, then the value is immediately overwritten by
  a `split("_", 1)`.
- **Packaging metadata is placeholder.** `setup.py` declares
  `author="Your Name"`, `url=".../yourusername"`, claims Python 3.8 support, and
  lists `install_requires=["mcp", "aiohttp", "python-dotenv"]` — two of which
  the code does not use, while the one it does use (pycurl) is missing.

## Design

### Structure

```
src/stocky_mcp/
  __init__.py        # public re-exports
  __main__.py        # python -m stocky_mcp
  config.py          # env-var configuration, parsed once
  models.py          # ImageResult
  cache.py           # TTLCache
  errors.py          # typed provider errors
  manager.py         # StockImageManager
  server.py          # FastMCP wiring
  providers/
    __init__.py
    base.py          # StockImageProvider ABC
    pexels.py
    unsplash.py
tests/
  ...
pyproject.toml       # replaces setup.py + setup.cfg
stocky_mcp.py        # backwards-compatibility shim
```

The root `stocky_mcp.py` is **kept deliberately**. The reporter of issue #10 —
and likely other users — has `python /path/to/stocky_mcp.py` in their client
config. The shim re-exports the public names and delegates to `main()`, so those
configs keep working.

### HTTP layer

`pycurl` is replaced with `httpx.AsyncClient`. This is a dependency *removal*,
not an addition: `mcp` already depends on `httpx`.

- One `AsyncClient` per provider, created in `__aenter__`, closed in `__aexit__`.
- Explicit connect/read timeouts so a slow provider cannot hang a tool call.
- Genuinely non-blocking, so the two providers are searched concurrently with
  `asyncio.gather` rather than sequentially.

### Caching

A small `TTLCache` in `cache.py`, wired into `StockImageManager.search` only —
never into downloads. The cache key is canonical: sorted provider list plus all
query parameters. Configured by `STOCKY_CACHE_TTL` (seconds, default 300);
`0` disables caching entirely.

### Error handling

Providers raise typed errors from `errors.py` (`ProviderAuthError`,
`ProviderRateLimitError`, `ProviderError`) instead of returning `[]` for every
failure. The manager catches them per-provider so one failing provider degrades
gracefully rather than failing the whole search, and the tool response reports
which providers errored and why. This replaces the current behaviour, where an
auth failure and a genuine zero-result search are indistinguishable.

### Testing

- `pytest` + `pytest-asyncio` + `pytest-cov`.
- Provider tests use `httpx.MockTransport` — no network, no monkeypatching of a
  C extension. This is the main practical payoff of the httpx migration.
- Server tests drive the real FastMCP app in-process over the SDK's in-memory
  transport, so tool registration and schemas are covered without spawning a
  subprocess.
- Tests that need real API keys are marked `@pytest.mark.integration` and skip
  automatically when keys are absent. They are not run in CI by default.
- Target ~90% statement coverage on `src/stocky_mcp`, with a `fail_under` floor
  enforced in CI.

The existing `test_stocky.py` and `test_mcp_client.py` are converted rather than
deleted: their network-dependent assertions become integration tests, and their
unit-testable parts become normal pytest cases.

### CI

- **test**: matrix over Python 3.10–3.13, dependency caching, pytest with
  coverage, coverage floor enforced.
- **lint**: `ruff check` and `ruff format --check`, replacing flake8 run with
  `--exit-zero` (which could never fail a build).
- **CodeQL**: retained as-is.
- Actions pinned to current major versions.

### Documentation

- `README.md`: corrected install and configuration instructions, full env-var
  table, `uvx` usage, attribution/licensing guidance, development and testing
  sections.
- `CONTRIBUTING.md`: new — dev setup, running tests, lint, release.
- `CHANGELOG.md`: new — Keep a Changelog format, documenting this pass.
- `.env.example`: updated to match the real configuration surface.

## Risks

- **Behaviour change on provider errors.** Callers that relied on an empty
  result list for auth failures will now see an explicit error field. This is
  the intended fix, and it is documented in the changelog.
- **Import path move.** `git` will show the main module as a move. The shim
  preserves runtime compatibility for both `python stocky_mcp.py` and
  `import stocky_mcp`.
- **Coverage floor.** Set to a level current tests actually meet, to avoid a
  permanently red build.

## Delivery

One branch, `chore/upkeep-2026-07`, with atomic reviewable commits in the order
above, left unpushed for review — local SSH push access is currently broken.
Issue and PR triage is performed through the authenticated `gh` API.

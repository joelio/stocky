# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

Nothing yet.

## [2.0.0] — 2026-07-28

A maintenance release covering packaging, correctness, testing and licence
compliance. The MCP tool surface is unchanged, so existing prompts keep
working, but several behaviours are deliberately different — see *Changed*.

### Added

- Search result caching with a configurable TTL (`STOCKY_CACHE_TTL`,
  default 300 seconds, `0` to disable).
- Attribution generation in the format each provider's licence requires,
  exposed as an `attribution` block on results.
- Unsplash download reporting. Their API guidelines require notifying the
  download endpoint whenever a user takes an image; Stocky now does.
- Search filters: `orientation` and `color`, validated per provider.
- A `stocky-mcp` console entry point, so clients can use `uvx stocky-mcp`
  with nothing installed.
- `python -m stocky_mcp` as an alternative entry point.
- Download safeguards: a size cap (`STOCKY_MAX_DOWNLOAD_BYTES`, 25 MiB) and
  optional confinement to a directory (`STOCKY_DOWNLOAD_ROOT`).
- Configuration options `STOCKY_HTTP_TIMEOUT`, `STOCKY_LOG_LEVEL` and
  `STOCKY_USER_AGENT`.
- All image size variants are now carried on each result, including the Pexels
  variants that have no canonical equivalent (`large2x`, `portrait`,
  `landscape`).
- A pytest suite of 241 tests at ~96% coverage, plus opt-in integration tests
  against the real APIs.
- `CONTRIBUTING.md` and this changelog.

### Changed

- **Breaking:** provider failures are now reported instead of being returned as
  an empty result list. A failed search includes an `errors` map naming the
  provider and the reason. Previously an invalid API key was indistinguishable
  from a search that genuinely matched nothing.
- **Breaking:** `pycurl` is replaced by `httpx`. This is a dependency removal —
  `mcp` already required `httpx`.
- Providers are now searched concurrently. The previous code was `async` in
  form only: it made blocking `pycurl` calls inside `async def`, stalling the
  event loop for the duration of every request.
- `per_page` is clamped per provider (Pexels 80, Unsplash 30). Unsplash
  silently falls back to 10 above its maximum, so an unclamped request for 50
  returned *fewer* images than a request for 30.
- Packaging moved to `pyproject.toml`; `setup.py`, `setup.cfg` and
  `requirements.txt` are gone. Minimum Python is now 3.10, matching the `mcp`
  SDK. The previous `>=3.8` claim was never satisfiable.
- The implementation moved into a `src/stocky_mcp/` package. The root
  `stocky_mcp.py` remains as a launcher so existing client configurations that
  invoke it by path keep working.
- The help resource is served as `text/markdown` rather than the default
  `text/plain`.
- CI now runs tests. The previous workflow only ran flake8 with `--exit-zero`,
  which could never fail a build. Linting moved from flake8 to ruff, with mypy
  added.

### Fixed

- Diagnostic output on a missing dependency went to **stdout**, corrupting the
  JSON-RPC stream. Clients saw this as a hang during `initialize` rather than
  a readable error. All output now goes to stderr, and the package logger no
  longer propagates to the root logger. Contributes to #10.
- `StockyServer.run` was `async def run(self): await self.mcp.run()`, awaiting
  a non-awaitable. `FastMCP.run` is synchronous.
- `pycurl` was imported before the guarded `mcp` import, so a missing pycurl
  produced a bare traceback and an immediate exit, which a client could only
  observe as a timeout. Also contributes to #10.
- curl handles leaked on every non-200 response, because `close()` was called
  after the early return.
- `PexelsProvider.search` never set `attribution_url`, while `get_details`
  did — the same image had different attribution depending on how it was
  fetched.
- `download_image` reconstructed the Pexels original by string-replacing
  `?h=650&w=940` out of a URL, which broke whenever Pexels changed its URL
  format. It now uses the real `src.original`.
- Unsplash rate limiting was treated as an authentication failure. Unsplash
  signals exhaustion with HTTP 403, not 429.
- Unsplash `description` is frequently null; results fell back to "Untitled"
  instead of the populated `alt_description`.
- Image ids containing underscores were mangled by prefix stripping.
- Downloads were unbounded, reading arbitrarily large responses into memory.
- Dead code in `get_image_details`: a prefix-matching loop assigned a variable
  that was immediately overwritten.
- README claimed Pexels requires no attribution. Their guidelines require a
  prominent link back to Pexels and, where possible, photographer credit.
- Package metadata contained placeholders (`author="Your Name"`,
  `url=".../yourusername"`) and listed dependencies the code never used
  (`aiohttp`, `python-dotenv`) while omitting the one it did.

### Removed

- `pycurl`, `aiohttp` and `python-dotenv` dependencies.
- The print-based `test_stocky.py` and `test_mcp_client.py` scripts, converted
  into the pytest suite and integration tests.
- `setup.py`, `setup.cfg`, `requirements.txt`.

### Security

- Downloads now refuse any non-image file extension. A download path arrives
  from a model-generated tool call, so without this the tool could be steered
  into writing bytes to `~/Library/LaunchAgents/x.plist` or a `.py` on the
  import path.
- Image URLs taken from provider responses are validated before being fetched.
  httpx ignores `base_url` for an absolute URL, so a hostile or compromised
  response could otherwise point the fetch at `169.254.169.254` or localhost.
  Private, loopback, link-local and non-HTTP URLs are refused.
- Image bytes are fetched with a separate, unauthenticated client. The
  provider client sends the API key on every request, and the image CDN is a
  different origin that has no business seeing it.
- Image fetches send `Accept-Encoding: identity`. The size cap was applied to
  decompressed bytes, so a small gzipped body could expand well past it before
  the limit was noticed.
- `request_json` now streams against a size cap. It previously buffered the
  whole body with no limit, so a ~200 KB compressed response could decode into
  roughly a gigabyte of memory.
- Provider-native image ids are validated before being interpolated into a URL
  path. httpx normalises dot segments, so `unsplash_../../me` reached a
  different authenticated endpoint on the provider's own API.
- API keys are excluded from `repr(Config)`, and stripped from provider error
  messages before they are logged or returned — some APIs echo the rejected
  credential back.
- Attribution HTML escapes photographer names and URLs, which are
  user-supplied content on both providers.
- Redirects are capped, and the root logger is pinned to stderr so a
  third-party library cannot corrupt the JSON-RPC stream.
- The PyPI publish action is pinned by commit rather than the mutable
  `release/v1` branch, and `persist-credentials: false` is set on checkout.

[Unreleased]: https://github.com/joelio/stocky/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/joelio/stocky/releases/tag/v2.0.0

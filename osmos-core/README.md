# osmos-core

Osmos's internal Instagram scraping engine — fully async, resumable, a
4-tier transport escalation ladder (anonymous → TLS-impersonated →
authenticated → headless browser). Used only as a library, imported by
`osmos`'s own code (`../src/osmos/collector.py`); not run standalone, no CLI
of its own.

Licensed under the terms in `LICENSE` (this directory). The timeline-query
fix (2026-10-15, Instagram migrated the endpoint this scraper calls) is
documented in `osmos_core/api/endpoints.py`'s docstring.

## Architecture

```
osmos_core/
  api/          endpoints, transports, escalation ladder, client, resolver
  auth/         cookie loading, persistence
  browser/      tier 4; imported lazily
  cache/        file and memory caches
  downloader/   streaming, resumable, atomic downloads (unused by osmos —
                osmos never downloads media, only profile/post text)
  extractors/   GraphQL, /api/v1 and HTML parsers
  models/       Media, Profile, Page, configuration
  pagination/   cursored async iterators
  retry/        backoff policy, adaptive rate limiter
  storage/      metadata (jsonl) and resume state
  utils/        logging, files, urls, shortcode maths
  cli/          typer app — kept for reference, not exposed as a script
  interfaces.py 11 Protocols; every component is injected
  errors.py     exception hierarchy
```

Design rules the original author enforced, still true: no global state,
every file under 400 lines, fully typed, transport errors translated at the
boundary, Instagram's field names live only in `extractors/`.

## Tests

```bash
cd osmos-core && python3.13 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

Pre-existing gap (not from the rename): `test_pagination.py`/
`test_integration.py` call `TimelinePaginator.fetch_page()` without
`username`, which the 2026-10-15 fix now requires. Not updated yet — if
touching this test suite, start there.

## Legal

Same as upstream: automated scraping is against Instagram's Terms of
Service regardless of tier. See the root `osmos` README's "Legal & ethics"
section — that's the operative one for how this is actually used here.

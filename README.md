# osmos

A PoC that collects Instagram influencer/creator profiles and classifies each
one into a content niche (Fashion & Style, Food & Cooking, Gaming & Esports,
...) using an LLM. `osmos-core/` (see its own `README.md`) is the fully async
scraping engine; a free-tier model on [OpenRouter](https://openrouter.ai/)
handles zero-shot classification.

**No media is ever downloaded.** This only reads public text (bio, captions,
hashtags); classification doesn't need images or video.

## Legal & ethics — read this first

**Automated scraping is against Instagram's Terms of Service**, whether or
not you are logged in, on any transport tier. This tool does not change that.

- Public profile data only, and only what a logged-out browser can already
  see — login (see "Auth" below) is used only because Instagram's anonymous
  API has become unreliable, never to reach data a logged-out visitor
  couldn't already see.
- A 2026 court ruling (the Bright Data case) held that logged-out collection
  of public Meta data isn't a *contract-law* breach in that specific dispute
  — that is not the same as Instagram's own Terms permitting it, and Meta
  still actively enforces against scraping (IP blocks, cease-and-desist,
  lawsuits) independent of that ruling.
- Respect robots directives, applicable law, and the privacy of the people
  whose profiles you're reading. Use this for small-scale research, not
  high-volume commercial harvesting.
- You are responsible for how you use this, same as `osmos-core`'s own Legal
  section says about itself.

## Quickstart

```bash
uv sync --extra dev
uv run osmos serve
```

That's it — `serve` opens a local web app at `localhost:8420` with everything
in it: a **Setup** tab for your OpenRouter API key (and optionally cookies,
proxy), a **Run** tab to collect + classify, and a live **Dashboard**. No
`.env` editing required for the API key; the Setup tab writes it for you.
Real-login auth (see "Auth" below, recommended) is `.env`-only — never typed
into the browser, same reasoning as never pasting a password there.

Prefer the terminal? Same thing works without the UI:

```bash
cp .env.example .env   # set OPENROUTER_API_KEY — a free key from https://openrouter.ai/keys
uv run osmos run data/seed_usernames.txt
uv run osmos export --format csv
```

Requires Python 3.13+ and [`uv`](https://docs.astral.sh/uv/). `git clone`
this repo and the two commands above are the whole setup — `osmos-core/`
ships inside it, nothing external to fetch or position correctly. It's a
separate codebase inside this one on purpose (own `pyproject.toml`, own
tests); see `osmos-core/README.md` for its architecture and
`osmos-core/LICENSE` for its terms.

## Commands

| Command | What it does |
|---|---|
| `osmos collect <usernames>` | Scrape profile + recent post metadata for each username into `osmos.db`. |
| `osmos classify` | Classify every profile that doesn't have a category yet. |
| `osmos run <usernames>` | `collect` then `classify` in one pass. |
| `osmos discover` | List candidate usernames mentioned across already-collected posts (see "Discovery" below). |
| `osmos export --format csv\|json` | Dump classified influencers. |
| `osmos stats` | Category breakdown of everything collected so far. |
| `osmos dashboard` | A static, shareable HTML snapshot — point-in-time, no server needed to view it. |
| `osmos serve` | The full interactive app — Setup / Run / live Dashboard, in your browser. |

`<usernames>` is either a path to a newline-delimited file (`#` comments
allowed — see `data/seed_usernames.txt`) or a comma-separated list, e.g.
`osmos collect nasa,natgeo,tasty`.

## How classification works

One call per profile to a free-tier model on OpenRouter (`dots-studio/dots-3-note-preview:free`
by default — see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md#model-choice)
for why OpenRouter and not a paid API), using OpenAI-compatible
`response_format: json_schema` structured output validated into a Pydantic
`ClassificationResult`, with a plain-prompt-JSON fallback for free models that
don't honour strict schema mode. The prompt is built from the profile's bio,
full name, external URL, and the top hashtags + a handful of sample captions
from its recent posts — see [`docs/TAXONOMY.md`](docs/TAXONOMY.md) for the
full category list and the reasoning behind it (why there's a secondary
category, why insufficient-data profiles never reach the API, why hashtags
are weighted below bio/captions).

## Discovery: where do the usernames come from?

`osmos-core` scrapes a *known* username's profile and timeline — it has no
hashtag search or explore-feed endpoint (verified by reading its
`api/endpoints.py`). So this PoC starts from a seed list
(`data/seed_usernames.txt`, ten diverse public brand/media accounts by
default) and offers one lightweight discovery mechanism on top:
`osmos discover` surfaces usernames `@mentioned` across posts you've already
collected, ranked by frequency, as candidates to add to your next `collect`
run. It's deliberately not a crawler — an unbounded "follow every mention"
expansion is exactly the kind of high-volume scraping that carries the most
ToS risk.

## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full pipeline
diagram, module responsibilities, and database schema. Short version:

```
seed usernames → collect (osmos-core) → SQLite → classify (OpenRouter) → SQLite → export/stats/discover
```

Every step reads/writes the SQLite database rather than passing data in
memory between commands — `osmos classify` always works off
`WHERE category IS NULL`, so it's resumable across runs, taxonomy changes,
and process restarts, the same way `osmos-core`'s own scraper resumes a
scrape from a saved page cursor.

## Project structure

```
src/osmos/
  config.py      Settings (.env + environment)
  taxonomy.py    the Category enum + descriptions
  collector.py   wraps osmos-core — profile + post metadata, no media
  aiograpi_collector.py  real-login collection path (see "Auth" above)
  features.py    the flat record a classification prompt is built from
  classifier.py  the system prompt + OpenRouter calls + insufficient-data guard
  storage.py     SQLite schema and every read/write
  pipeline.py    collect -> classify orchestration
  dashboard.py   the static HTML report (chart + table), and stats shared with web.py
  web.py         the live app — FastAPI routes + the Setup/Run/Dashboard page
  usernames.py   shared parsing: a file, a comma list, or a textarea's raw text
  cli.py         the `osmos` Typer app
tests/           15 tests, fabricated fixtures, no network required
data/            seed_usernames.txt
docs/            ARCHITECTURE.md, TAXONOMY.md
.claude/skills/influencer-pipeline/   the project skill for Claude Code sessions
```

## Testing

```bash
uv run pytest
```

17 tests covering hashtag ranking, caption truncation, prompt building, and
the full collect → classify → fetch → discover database round-trip, all
against fabricated fixtures — no live network call, no API key needed. The
live OpenRouter call and live Instagram scrape are integration points this
suite deliberately doesn't mock; both paths are also verified live end-to-end
(see "Auth: two ways to collect" below) — `osmos classify` against a real
OpenRouter key, and `osmos collect` against real Instagram.

## Auth: two ways to collect

`osmos collect` needs *some* authenticated path to Instagram — a fully
anonymous request gets `401 require_login` immediately, confirmed on
multiple networks and, separately, confirmed unrelated to IP reputation (a
fresh paid residential proxy made no difference). Two options, weakest to
strongest:

1. **Pasted cookies** (`COOKIES_PATH`) — osmos-core's own transport ladder,
   cookies exported from a logged-in browser session. Works for resolving a
   profile, but Instagram treats a borrowed cookie jar as a markedly weaker
   signal than a real session — it's the first thing to try, not the most
   reliable.
2. **Real login** (`INSTAGRAM_USERNAME` / `INSTAGRAM_PASSWORD`, recommended)
   — a genuine `accounts/login/` private-API session via
   [`aiograpi`](https://github.com/subzeroid/aiograpi) (async, actively
   maintained, MIT-licensed). This is what instagrapi's own source confirms
   real Instagram clients do: `user_info_by_username` in their codebase
   prefers a logged-in private-API session over the anonymous public
   endpoint, and even their "public" GraphQL path injects a real `sessionid`
   cookie first. `src/osmos/aiograpi_collector.py` does the same — login
   once, the session is cached to `IG_SESSION_PATH` (`ig_session.json` by
   default) so later runs don't need to re-authenticate.

   **Use a disposable account, never your main one.** Automated login
   carries real challenge/ban risk, and a first login from a new network
   commonly triggers a one-time email/2FA code —
   `INSTAGRAM_VERIFICATION_CODE` in `.env` takes it for that first run only;
   it's not needed again once the session is cached.

When both are configured, `collector.collect_many()` prefers the real-login
path automatically. Live-verified 2026-10-15: logged in, resolved `espn`
(28.8M followers), collected 5 posts, classified `Sports` at confidence 1.0
— the full pipeline, against live Instagram and a live OpenRouter key.

## Extending

- **New category:** add it to `taxonomy.py` — the classifier's system prompt
  picks it up automatically. See `docs/TAXONOMY.md`.
- **Private accounts, stories, highlights:** set `INSTAGRAM_USERNAME`/
  `INSTAGRAM_PASSWORD` in `.env` for a real logged-in session (see "Auth"
  above) — a private account's posts need a session that actually follows
  it, which pasted cookies alone don't give you. Treat that account as
  disposable; Instagram restricts accounts for automated traffic.
- **A different storage backend:** `storage.py` is the only module that knows
  about SQLite; swapping it for Postgres means changing one file.
- **Smarter discovery:** `storage.top_mentions` is a frequency count over
  `@mentions` already in the database — a real engagement-graph crawl (BFS
  over mentions/tags with a depth limit) would be the natural next step, and
  is deliberately not what this PoC does by default (see "Discovery" above).

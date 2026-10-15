---
name: influencer-pipeline
description: Collect Instagram influencer profiles with osmos-core and classify them into content niches with a free OpenRouter model. Use when the user asks to scrape/collect Instagram influencers or creators, classify accounts by category/niche, extend this project's taxonomy or seed list, or debug the osmos collect/classify pipeline.
---

# Instagram influencer collect + classify pipeline

This project (`osmos`, in this directory) scrapes Instagram profiles with the
local `osmos-core` library (sibling directory `../osmos-core-main`) and
classifies each one into a content niche with a free-tier model on
OpenRouter. Full design rationale: [`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md).
Taxonomy and why it's shaped this way: [`docs/TAXONOMY.md`](../../docs/TAXONOMY.md).

## Running it

```bash
uv sync --extra dev
uv run osmos serve                          # the full app: Setup/Run/Dashboard in the browser
```

Or via the CLI directly:

```bash
cp .env.example .env         # then set OPENROUTER_API_KEY — free key at https://openrouter.ai/keys

uv run osmos run data/seed_usernames.txt   # collect + classify
uv run osmos collect <usernames.txt>        # scrape only, no media downloaded
uv run osmos classify                       # classify whatever's pending
uv run osmos discover                       # candidate usernames from @mentions
uv run osmos export --format csv            # dump results
uv run osmos stats                          # category breakdown
uv run osmos dashboard                      # static shareable HTML snapshot
uv run pytest                               # 17 tests, no network required
```

`osmos serve`'s Setup tab writes `.env` for you for the OpenRouter key,
cookies and proxy. It still never takes an Instagram username/password
through the browser — that stronger auth path (`INSTAGRAM_USERNAME`/
`PASSWORD`, see README's "Auth" section and `src/osmos/aiograpi_collector.py`)
is `.env`-only by design, not because it doesn't exist. If asked to add
Instagram login to the *web form*: don't — it's deliberately kept out of the
browser even though the project supports it via `.env`.

Usernames can be a path to a newline-delimited file (`#` comments allowed, see
`data/seed_usernames.txt`) or a comma-separated list passed directly.

## Where things live

- `src/osmos/taxonomy.py` — the category list. Add a category here (enum
  member + description); the classifier's system prompt picks it up
  automatically. No other file needs to change.
- `src/osmos/classifier.py` — the system prompt and the per-profile
  OpenRouter call. `CLASSIFIER_MODEL` env var controls which model (defaults
  to a free slug, `dots-studio/dots-3-note-preview:free` — live-verified
  working; free slugs rotate, swap it for another from
  https://openrouter.ai/models?max_price=0 if it stops working — see
  ARCHITECTURE.md's "Model choice").
- `src/osmos/storage.py` — the SQLite schema and every query. `osmos.db`
  (path from `DB_PATH`) is the single source of truth between pipeline steps.
- `data/seed_usernames.txt` — the demo seed list. Add more usernames here, or
  pass a different file to any command.

## Known limitation: anonymous-tier blocking

Instagram's anonymous HTTP tier returns `401 require_login=true` ("please
wait a few minutes") essentially always now — confirmed this is *not* an
IP-reputation thing (a fresh paid residential proxy, zero history, made no
difference). If `osmos collect` fails this way, the fix is auth, not network:

1. Set `INSTAGRAM_USERNAME`/`INSTAGRAM_PASSWORD` in `.env` (a disposable
   account) — real login is markedly stronger than osmos-core's cookie tiers.
   See README's "Auth: two ways to collect" and `src/osmos/aiograpi_collector.py`.
2. First login from a new session commonly asks for a one-time email/2FA
   code — set `INSTAGRAM_VERIFICATION_CODE` for that one run; the session
   then caches to `IG_SESSION_PATH` and later runs don't need it again.
3. A proxy (`PROXY_URL`) still matters for IP-level rate limiting on *already
   logged-in* requests, just not for this specific `require_login` wall.

The full pipeline's logic (collect → features → classify → store → export →
discover) is covered by `pytest` with fabricated fixtures, independent of
live network access — that suite is the thing to trust when live scraping is
blocked by network conditions outside this project's control.

## Legal reminder

Scraping violates Instagram's Terms of Service regardless of which tier
answers — see the README's Legal & Ethics section before pointing this at
anything beyond small-scale public-profile research. This project never
downloads media, and only reads data a logged-out visitor could already see
even when a real login is configured for a stronger auth signal.

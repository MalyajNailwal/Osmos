# Architecture

## Pipeline

```
seed usernames (data/seed_usernames.txt, a file, or a comma list)
        │
        ▼
┌───────────────────┐   osmos_core.InstagramClient by default (anonymous tier,
│  collector.py      │   cookie tier if COOKIES_PATH is set) — or delegates to
│  collect_many()    │   aiograpi_collector's real login when INSTAGRAM_USERNAME/
└─────────┬──────────┘   PASSWORD are set (stronger signal, see README's "Auth").
          ▼
┌───────────────────┐   SQLite. The single source of truth between steps —
│  storage.py        │   collect writes here, classify reads its input back
│  save_collected()  │   from here, never from in-memory scrape results.
└─────────┬──────────┘
          ▼
┌───────────────────┐   Rebuilds InfluencerFeatures (bio, top hashtags,
│  storage.py        │   sample captions) from stored rows — works identically
│  load_features()   │   whether called right after collect or days later.
└─────────┬──────────┘
          ▼
┌───────────────────┐   One structured-output call per profile to a free
│  classifier.py     │   OpenRouter model by default. Pydantic ClassificationResult:
│  classify_many()   │   category, secondary_category, confidence, reasoning.
└─────────┬──────────┘
          ▼
┌───────────────────┐
│  storage.py         │   category/confidence/reasoning written back onto the
│  save_classification│   same influencers row.
└───────────────────┘

                osmos export / osmos stats / osmos discover
                read from the database at any point, independently.
```

Every step is a separate CLI command (`collect`, `classify`) that only talks
to the database — `osmos run` is a convenience wrapper that calls both in
sequence. This is the same resumability principle osmos-core itself uses for
scraping (state written after every page): `osmos classify` always operates
on `WHERE category IS NULL`, so a crashed or interrupted run, a taxonomy
change, or simply running `collect` again on a bigger seed list all just work
by re-running the next command.

## Module responsibilities

| Module | Owns |
|---|---|
| `config.py` | The one `Settings` object (`.env` + environment), read once. |
| `taxonomy.py` | The `Category` enum and its descriptions — the only thing a taxonomy change touches. |
| `collector.py` | Talking to osmos-core: `CollectedInfluencer` (`Profile` + `list[Media]`), per-account error handling; delegates to `aiograpi_collector` when real login is configured. |
| `aiograpi_collector.py` | Real-login collection via `aiograpi`'s private API — login, session caching (`IG_SESSION_PATH`), mapping its `User`/`Media` into the same `Profile`/`Media` shapes so nothing downstream changes. |
| `features.py` | `InfluencerFeatures` — the flat, osmos-core-independent record a classification prompt is built from, plus `rank_hashtags`/`truncate_captions`. |
| `classifier.py` | The system prompt, `ClassificationResult`, the insufficient-data guard, and the batched OpenRouter calls (with schema-mode fallback and 429/5xx retry). |
| `storage.py` | The SQLite schema and every read/write — collect, classify input, classification results, export, and `top_mentions` (discovery). |
| `pipeline.py` | `run_collect` / `run_classify` — orchestration only, no business logic of its own. |
| `cli.py` | Typer commands: `collect`, `classify`, `run`, `discover`, `export`, `stats`. |

No module imports "backwards" — `collector → features → classifier → storage → pipeline → cli`
is a straight line, so there's no import cycle to reason about.

## Why no discovery endpoint

osmos-core is a **profile scraper**, not a search engine: given a username it
returns a rich profile + timeline, but there is no hashtag search, explore
feed, or similar discovery endpoint (confirmed by reading `api/endpoints.py` —
the full URL surface osmos-core talks to). This isn't just an osmos-core gap —
`aiograpi` (`../aiograpi-main`, a much larger instagrapi-fork with hashtag,
explore, location and fbsearch mixins) confirms it's Instagram's own current
restriction: its changelog notes those "high-level hashtag/location helpers"
were "moved to authenticated private/mobile flows" in its `1.0.0` baseline —
anonymous hashtag/explore discovery doesn't exist on modern Instagram at all,
not only in osmos-core. Getting it back means full account login through
aiograpi's private API, which its own README calls out as suited to
"testing or research" rather than production, with real ban risk (challenges,
checkpoints, 2FA) and proxy/account costs its README recommends a paid
service for instead. That's a materially different risk profile than this
PoC's — not something to take on for a discovery nice-to-have. So "collecting
the influencers" has two legitimate starting points here instead:

1. **Seed list** (`data/seed_usernames.txt`) — the primary path. You supply
   known accounts; `osmos` enriches and classifies them.
2. **`osmos discover`** — once you've collected some accounts, their post
   captions carry `@mentions` (shout-outs, collabs, brand tags). `discover`
   ranks usernames mentioned across stored posts that aren't already in the
   database, giving you a candidate list to review and feed into the next
   `collect` run. It's a weak discovery signal, not a crawler — by design,
   since an unbounded "follow every mention" crawl is exactly the kind of
   high-volume scraping that carries the most ToS/legal risk (see the
   README's Legal & Ethics section).

## Database schema

```sql
CREATE TABLE influencers (
    username TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    full_name TEXT,
    biography TEXT,
    external_url TEXT,
    is_private INTEGER NOT NULL,      -- 0/1
    is_verified INTEGER NOT NULL,     -- 0/1
    is_business INTEGER NOT NULL,     -- 0/1
    follower_count INTEGER,
    following_count INTEGER,
    media_count INTEGER,
    profile_pic_url TEXT,
    scraped_at TEXT NOT NULL,         -- ISO 8601 UTC
    category TEXT,                   -- NULL until classified
    secondary_category TEXT,
    confidence REAL,
    reasoning TEXT,
    classified_at TEXT                -- ISO 8601 UTC
);

CREATE TABLE posts (
    shortcode TEXT NOT NULL,
    username TEXT NOT NULL REFERENCES influencers(username),
    caption TEXT,
    hashtags TEXT NOT NULL,          -- JSON array
    mentions TEXT NOT NULL,          -- JSON array
    like_count INTEGER,
    comment_count INTEGER,
    timestamp TEXT,                  -- ISO 8601 UTC
    permalink TEXT,
    PRIMARY KEY (username, shortcode)
);
```

`collect` upserts `influencers` and replaces that account's `posts` rows —
re-scraping never touches the classification columns, so a re-collect doesn't
discard a previous classification.

## Model choice

Classification calls a free-tier model on [OpenRouter](https://openrouter.ai/)
(`dots-studio/dots-3-note-preview:free` by default) directly over HTTP — this
is a deliberate choice, not a stopgap: it's what's actually usable without a
paid key, and it's live-verified working (`osmos classify` against a real
OpenRouter key correctly classified a test profile, schema-constrained
output, first model tried). Free model slugs on OpenRouter rotate over time;
if the configured one starts failing, `CLASSIFIER_MODEL` in `.env` takes any
slug from https://openrouter.ai/models?max_price=0, no code change needed.

This earlier used Anthropic's native `messages.parse()`, which
schema-constrains generation server-side — a stronger guarantee than
OpenRouter can promise across 14 different free models of wildly varying
size and training. Losing that guarantee is the real cost of this choice, and
`classifier.py` compensates for it directly rather than assuming it away:

- `classify_one` tries strict `response_format: json_schema` first, and falls
  back to a plain "respond with only this JSON" prompt instruction + manual
  parsing if a model doesn't honour schema mode (not every free model does).
- `_call_openrouter` retries 429/5xx with backoff — `httpx` has no automatic
  retry the way the Anthropic SDK did, so this is now explicit rather than
  free.
- `_clean_json` strips markdown code fences some open-weight models wrap JSON
  in despite being told not to.

**`567-labs/instructor` was reconsidered here, not just dismissed again.**
This is now exactly the situation instructor exists for — Pydantic validation
against a provider without a native structured-output guarantee. Still
decided against it for now: the hand-rolled version above is about 20 lines,
already proven working, and avoids pulling in `instructor` plus an
OpenAI-compatible client to replicate logic that small. The real gap
instructor would close is retry-with-validation-feedback (re-prompting a
model with *why* its JSON failed to validate, not just asking again) — worth
revisiting if JSON-parse failures turn out to be common across the 14
available free models in practice, not before.

## Roadmap: cheaper classification at scale

Zero-shot LLM calls are the right choice for v1 — there's no labeled
dataset to train anything else on yet. Once there's real classified volume,
the standard cost-reduction path is **bootstrap → correct → distill**:

1. Run `osmos classify` at real volume; the LLM's output is a cheap first
   label for every profile.
2. Have a human spot-check and correct a sample of those results. That
   correction pass doubles as a labeled dataset — it's a sanity check worth
   doing anyway, not extra labeling work invented for this purpose.
3. Once there are roughly 8-16 corrected examples per category, train a
   [SetFit](https://github.com/huggingface/setfit) few-shot classifier on
   them. Inference then runs locally (sentence-transformers + a small head),
   no API cost or rate limits — this is what matters once per-profile API
   calls start adding up at real scale, or once free-tier rate limits start
   being the bottleneck instead of money.

Not worth building before that volume and labeled set exist: SetFit pulls in
a `sentence-transformers` + torch dependency weight comparable to the
optional browser tier, for a training step that has nothing to train on yet.

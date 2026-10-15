# Category taxonomy

`osmos` classifies each profile into exactly one primary category from a
fixed list, plus an optional `secondary_category` for accounts that clearly
span two niches. Defined in [`src/osmos/taxonomy.py`](../src/osmos/taxonomy.py).

Real influencer-marketing platforms (HypeAuditor, Modash) don't actually use
a closed taxonomy — they run open keyword/AI search over free-text labels.
A closed list here is a concession to needing an LLM to commit to exactly one
answer per profile in a structured-output call, not an industry standard
being mirrored.

| Category | Description |
|---|---|
| Fashion & Style | Outfits, styling, fashion brands, model/editorial content. |
| Beauty & Skincare | Makeup, skincare routines, haircare, beauty product reviews. |
| Fitness & Health | Workouts, gym content, nutrition, physical wellness, body transformation. |
| Food & Cooking | Recipes, restaurant reviews, cooking tutorials, food photography. |
| Travel | Destinations, travel guides, trip vlogs, hotel/flight content. |
| Technology & Gadgets | Consumer electronics, software, apps, product reviews, tech news. |
| Gaming & Esports | Video games, streaming, esports, gaming gear. |
| Business & Finance | Entrepreneurship, investing, personal finance, career/business advice. |
| Parenting & Family | Family life, parenting tips, kids' content, pregnancy/motherhood. |
| Pets & Animals | Pet accounts, animal care, wildlife content. |
| Comedy & Entertainment | Sketches, memes, pop culture commentary, general entertainment. |
| Music | Musicians, singers, producers, music performance/reviews. |
| Art & Design | Illustration, painting, graphic/product design, creative process content. |
| Education & Learning | Teaching, explainers, study content, academic/skill-building material. |
| Lifestyle & Vlogging | Day-in-the-life, general personal vlogging that doesn't fit a narrower niche. |
| Automotive | Cars, motorcycles, car culture, reviews and builds. |
| Sports | Athletes, sports commentary, fandom content (distinct from personal fitness). |
| Photography | Photography as the subject itself (gear, technique, portfolio accounts). |
| Home & Interior Design | Interior design, home decor, renovation, organization content. |
| Other / Uncategorized | Public figures, brands, or accounts that don't fit a niche above — **and** the result for any profile with no bio and no captions to classify from (see below). |

## Design decisions, and why

- **Fashion & Style vs. Beauty & Skincare overlap heavily in practice** (same
  creators do both). Rather than force a single split, accept the overlap —
  this is what `secondary_category` is for.
- **"Other / Uncategorized" is not optional.** A closed taxonomy forces every
  account into a bucket; without a real fallback, borderline accounts get
  shoehorned into whichever category happens to score highest, which looks
  confident and is often wrong.
- **Insufficient data is handled in code, not left to the model.** A profile
  with an empty bio and no captions never reaches the LLM at all —
  `classifier._has_signal()` short-circuits straight to `Other` with
  `confidence=0.0` and a `reasoning` that says so. Zero-shot classification
  from nothing is a guess wearing a category label; it's more honest (and
  cheaper) to say "no signal" in code than to hope the model volunteers that.
- **Hashtags are weighted below bio/captions in the prompt.** Generic growth
  hashtags (`#instagood`, `#follow4follow`) are common and largely
  content-independent; the system prompt explicitly tells the model to weigh
  bio and captions more heavily.

## Extending the taxonomy

Add a member to the `Category` enum and a matching entry in
`CATEGORY_DESCRIPTIONS` in `taxonomy.py` — both are consumed automatically by
the classifier's system prompt. After a taxonomy change, re-run
`osmos classify` on previously-classified profiles to pick up the new
category (it only ever classifies rows where `category IS NULL`, so you'd
need to clear `category` for the rows you want reclassified, e.g.
`UPDATE influencers SET category = NULL WHERE category = 'Lifestyle & Vlogging'`).

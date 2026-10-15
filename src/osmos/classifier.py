"""LLM-based zero-shot classification of a scraped influencer profile.

Calls OpenRouter directly over HTTP (its chat-completions endpoint is
OpenAI-compatible) using a free-tier model by default — this is the real
classification path, not a fallback behind a paid provider. Free model slugs
rotate on OpenRouter; if the configured one stops working, swap
CLASSIFIER_MODEL in .env for another from https://openrouter.ai/models?max_price=0.

Three things came out of actually testing this rather than assuming it would
work: (1) not every free model honours strict JSON-schema mode, so
`classify_one` tries schema-constrained generation first and falls back to a
plain prompt instruction + manual parsing if that errors; (2) `httpx` has no
built-in retry the way the Anthropic SDK does, so `_call_openrouter` retries
429/5xx itself with a short backoff; (3) open-weight models sometimes wrap
JSON in markdown fences despite being told not to — `_clean_json` strips that.

Two things came out of researching classification practice specifically:
(1) a profile with no bio and no captions never reaches the API at all —
`_has_signal` short-circuits it, because a zero-shot label on empty input is
a guess dressed up as a result, not a classification; (2) the result carries
an optional `secondary_category`, because forcing a single label onto a
multi-niche account (fashion-and-beauty creators are the classic case) is
where zero-shot accuracy drops the most.
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx
from pydantic import BaseModel, Field, ValidationError

from .config import settings
from .features import InfluencerFeatures
from .taxonomy import CATEGORY_DESCRIPTIONS, Category

logger = logging.getLogger(__name__)

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3

_TAXONOMY_BLOCK = "\n".join(f"- {c.value}: {desc}" for c, desc in CATEGORY_DESCRIPTIONS.items())

_SYSTEM_PROMPT = f"""You classify Instagram creator accounts into exactly one primary content \
niche based on their bio, recent post captions and hashtags.

Categories:
{_TAXONOMY_BLOCK}

Rules:
- Pick the single best-fitting primary category, even for borderline accounts.
- Use "Other / Uncategorized" only when the account is a brand, public figure, \
meme/repost page, or genuinely has no clear content niche.
- Set secondary_category when the account clearly spans two niches (e.g. a \
fashion-and-beauty creator); leave it null otherwise — most accounts don't need one.
- Weigh the bio and captions more heavily than hashtags: hashtags are often \
generic growth tags unrelated to what the account actually posts about.
- confidence reflects how unambiguous the signal is, not how famous the account is.
- reasoning is one short sentence citing the specific signal used."""

_INSUFFICIENT_DATA = "insufficient data: no bio or recent captions were available to classify from"


class ClassificationResult(BaseModel):
    category: Category
    secondary_category: Category | None = Field(
        default=None, description="A second niche the account also touches, when relevant."
    )
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(max_length=300)


_RESULT_SCHEMA = ClassificationResult.model_json_schema()
_JSON_ONLY_INSTRUCTION = (
    "\n\nRespond with ONLY a single JSON object matching this schema, no prose, "
    f"no markdown fences:\n{json.dumps(_RESULT_SCHEMA)}"
)


def _has_signal(features: InfluencerFeatures) -> bool:
    """Whether there's enough text to classify from — bio or at least one caption."""
    return bool(features.biography) or bool(features.sample_captions)


def build_prompt(features: InfluencerFeatures) -> str:
    """Render the bounded feature text a single classification call sees."""
    captions = [f"  - {c}" for c in features.sample_captions] or ["  - (no captions available)"]
    lines = [
        f"username: @{features.username}",
        f"full_name: {features.full_name or '-'}",
        f"bio: {features.biography or '-'}",
        f"external_url: {features.external_url or '-'}",
        f"follower_count: {features.follower_count if features.follower_count is not None else 'unknown'}",
        f"is_verified: {features.is_verified}",
        f"is_business_account: {features.is_business}",
        f"top_hashtags: {', '.join(features.top_hashtags) or '-'}",
        "sample_captions:",
        *captions,
    ]
    return "\n".join(lines)


def _clean_json(content: str) -> str:
    """Strip markdown code fences some models wrap JSON in despite instructions."""
    text = content.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return text


async def _call_openrouter(client: httpx.AsyncClient, prompt: str, *, use_response_format: bool) -> str:
    """One chat-completions call, retried on transient (429/5xx) failures.

    Returns the raw message content string. Raises ``httpx.HTTPStatusError``
    for anything non-transient (bad request, invalid key, model not found).
    """
    payload: dict = {
        "model": settings.classifier_model,
        "messages": [
            {
                "role": "system",
                "content": _SYSTEM_PROMPT + ("" if use_response_format else _JSON_ONLY_INSTRUCTION),
            },
            {"role": "user", "content": prompt},
        ],
    }
    if use_response_format:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "ClassificationResult", "strict": True, "schema": _RESULT_SCHEMA},
        }

    response = None
    for attempt in range(_MAX_ATTEMPTS):
        response = await client.post(_OPENROUTER_URL, json=payload)
        if response.status_code not in _RETRYABLE_STATUS:
            break
        if attempt < _MAX_ATTEMPTS - 1:
            await asyncio.sleep(2**attempt)  # 1s, 2s
    assert response is not None
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


async def classify_one(client: httpx.AsyncClient, features: InfluencerFeatures) -> ClassificationResult:
    if not _has_signal(features):
        return ClassificationResult(category=Category.OTHER, confidence=0.0, reasoning=_INSUFFICIENT_DATA)

    prompt = build_prompt(features)
    try:
        content = await _call_openrouter(client, prompt, use_response_format=True)
        return ClassificationResult.model_validate_json(_clean_json(content))
    except (httpx.HTTPStatusError, ValidationError) as exc:
        # Not every free model honours strict JSON-schema mode — fall back to
        # a plain prompt instruction and parse whatever comes back.
        logger.debug("structured mode failed (%s), retrying with prompt-only JSON", exc)
        content = await _call_openrouter(client, prompt, use_response_format=False)
        return ClassificationResult.model_validate_json(_clean_json(content))


async def classify_many(
    features: list[InfluencerFeatures],
    concurrency: int | None = None,
) -> dict[str, ClassificationResult | None]:
    """Classify a batch, tolerating per-profile failures.

    A ``None`` value means that profile's call failed (missing/invalid key,
    rate limit exhausted after retries, both schema and fallback modes
    failed to parse) — it stays unclassified and is picked up again by the
    next ``osmos classify`` run.
    """
    semaphore = asyncio.Semaphore(concurrency or settings.classifier_concurrency)
    results: dict[str, ClassificationResult | None] = {}
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key or ''}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(120.0)) as client:

        async def _bounded(item: InfluencerFeatures) -> None:
            async with semaphore:
                try:
                    results[item.username] = await classify_one(client, item)
                except (httpx.HTTPStatusError, httpx.RequestError, ValidationError) as exc:
                    logger.warning("classification failed for %s: %s", item.username, exc)
                    results[item.username] = None

        await asyncio.gather(*(_bounded(item) for item in features))

    return results

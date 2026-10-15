"""The flat record a classification call is built from.

Deliberately decoupled from osmos_core's Profile/Media models: `osmos classify`
always rebuilds this from whatever is in the database, independent of whether
this run just scraped the profile or is reclassifying something collected
days ago (e.g. after a taxonomy change). `from_collected` exists for the one
case that doesn't round-trip through the database — tests exercising the
classifier's prompt-building in isolation.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from .collector import CollectedInfluencer

MAX_CAPTIONS = 5
MAX_CAPTION_CHARS = 200
MAX_HASHTAGS = 15


@dataclass(slots=True)
class InfluencerFeatures:
    username: str
    full_name: str | None
    biography: str | None
    external_url: str | None
    follower_count: int | None
    is_verified: bool
    is_business: bool
    top_hashtags: list[str] = field(default_factory=list)
    sample_captions: list[str] = field(default_factory=list)


def rank_hashtags(tag_lists: Iterable[list[str]], limit: int = MAX_HASHTAGS) -> list[str]:
    """Most frequent hashtags across a set of posts, most common first."""
    counts: dict[str, int] = {}
    for tags in tag_lists:
        for tag in tags:
            counts[tag] = counts.get(tag, 0) + 1
    return [tag for tag, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:limit]]


def truncate_captions(
    captions: Iterable[str | None], limit: int = MAX_CAPTIONS, max_chars: int = MAX_CAPTION_CHARS
) -> list[str]:
    """Strip, drop empties, cap length — bounds token usage per classification call."""
    out: list[str] = []
    for caption in captions:
        text = (caption or "").strip()
        if text:
            out.append(text[:max_chars])
        if len(out) >= limit:
            break
    return out


def from_collected(collected: CollectedInfluencer) -> InfluencerFeatures:
    profile = collected.profile
    return InfluencerFeatures(
        username=profile.username,
        full_name=profile.full_name,
        biography=profile.biography,
        external_url=str(profile.external_url) if profile.external_url else None,
        follower_count=profile.follower_count,
        is_verified=profile.is_verified,
        is_business=profile.is_business,
        top_hashtags=rank_hashtags(post.hashtags for post in collected.posts),
        sample_captions=truncate_captions(post.caption for post in collected.posts),
    )

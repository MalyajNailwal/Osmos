from __future__ import annotations

from datetime import UTC, datetime

from osmos_core.models.media import Media, MediaType
from osmos_core.models.profile import Profile

from osmos.classifier import build_prompt
from osmos.collector import CollectedInfluencer
from osmos.features import from_collected, rank_hashtags, truncate_captions


def _profile(**overrides: object) -> Profile:
    base: dict[str, object] = {
        "user_id": "1",
        "username": "chefjane",
        "full_name": "Jane",
        "biography": "Home cook sharing recipes",
        "follower_count": 10_000,
        "is_verified": False,
        "is_business": True,
    }
    base.update(overrides)
    return Profile(**base)


def _media(caption: str) -> Media:
    return Media(
        id="1",
        shortcode="abc",
        media_type=MediaType.IMAGE,
        owner_id="1",
        username="chefjane",
        caption=caption,
        timestamp=datetime.now(UTC),
    )


def test_rank_hashtags_orders_by_frequency_then_truncates() -> None:
    assert rank_hashtags([["a", "b"], ["a"]]) == ["a", "b"]
    assert rank_hashtags([["a", "b", "c"]], limit=2) == ["a", "b"]


def test_truncate_captions_drops_empty_and_caps_length() -> None:
    out = truncate_captions(["  hi  ", "", None, "x" * 300], max_chars=5)
    assert out == ["hi", "x" * 5]


def test_truncate_captions_respects_limit() -> None:
    out = truncate_captions([f"caption {i}" for i in range(10)], limit=3)
    assert len(out) == 3


def test_from_collected_builds_features_from_posts() -> None:
    collected = CollectedInfluencer(
        profile=_profile(), posts=[_media("Best #pasta recipe ever #cooking")]
    )
    features = from_collected(collected)
    assert features.username == "chefjane"
    assert "pasta" in features.top_hashtags
    assert features.sample_captions


def test_build_prompt_includes_bio_and_hashtags() -> None:
    features = from_collected(CollectedInfluencer(profile=_profile(), posts=[_media("#pasta night")]))
    prompt = build_prompt(features)
    assert "chefjane" in prompt
    assert "pasta" in prompt
    assert "Home cook sharing recipes" in prompt

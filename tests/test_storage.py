from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from osmos_core.models.media import Media, MediaType
from osmos_core.models.profile import Profile

from osmos import storage
from osmos.classifier import ClassificationResult
from osmos.collector import CollectedInfluencer
from osmos.taxonomy import Category


def _profile() -> Profile:
    return Profile(user_id="1", username="chefjane", biography="recipes", follower_count=100)


def _media() -> Media:
    return Media(
        id="1",
        shortcode="abc",
        media_type=MediaType.IMAGE,
        owner_id="1",
        username="chefjane",
        caption="#pasta night",
        timestamp=datetime.now(UTC),
    )


def test_round_trip_collect_classify_fetch(tmp_path: Path) -> None:
    conn = storage.connect(tmp_path / "test.db")
    storage.save_collected(conn, CollectedInfluencer(profile=_profile(), posts=[_media()]))

    assert storage.unclassified_usernames(conn) == ["chefjane"]

    features = storage.load_features(conn, "chefjane")
    assert "pasta" in features.top_hashtags

    storage.save_classification(
        conn,
        "chefjane",
        ClassificationResult(category=Category.FOOD_COOKING, confidence=0.9, reasoning="recipes"),
    )
    assert storage.unclassified_usernames(conn) == []

    rows = storage.fetch_all(conn, category=Category.FOOD_COOKING.value)
    assert rows[0]["username"] == "chefjane"


def test_recollect_does_not_wipe_an_existing_classification(tmp_path: Path) -> None:
    conn = storage.connect(tmp_path / "test.db")
    storage.save_collected(conn, CollectedInfluencer(profile=_profile(), posts=[_media()]))
    storage.save_classification(
        conn,
        "chefjane",
        ClassificationResult(category=Category.FOOD_COOKING, confidence=0.9, reasoning="recipes"),
    )

    storage.save_collected(conn, CollectedInfluencer(profile=_profile(), posts=[_media()]))

    rows = storage.fetch_all(conn)
    assert rows[0]["category"] == Category.FOOD_COOKING.value


def test_top_mentions_excludes_known_usernames(tmp_path: Path) -> None:
    conn = storage.connect(tmp_path / "test.db")
    storage.save_collected(conn, CollectedInfluencer(profile=_profile(), posts=[]))
    conn.execute(
        "INSERT INTO posts (shortcode, username, hashtags, mentions) VALUES (?, ?, ?, ?)",
        ("x", "chefjane", "[]", '["newfoodie", "newfoodie", "chefjane"]'),
    )
    conn.commit()

    candidates = storage.top_mentions(conn, min_count=1)
    assert ("newfoodie", 2) in candidates
    assert all(u != "chefjane" for u, _ in candidates)

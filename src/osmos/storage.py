"""SQLite persistence — the whole store, intentionally undecorated.

Two tables and a handful of functions; a PoC this size doesn't earn an ORM.
The database is the single source of truth between pipeline steps: `collect`
writes to it, `classify` reads its input back from it (never from in-memory
scrape results), which is what lets `osmos classify` run standalone, any time
after `osmos collect`, and resume cleanly across process restarts.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .classifier import ClassificationResult
from .collector import CollectedInfluencer
from .features import InfluencerFeatures, rank_hashtags, truncate_captions

_SCHEMA = """
CREATE TABLE IF NOT EXISTS influencers (
    username TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    full_name TEXT,
    biography TEXT,
    external_url TEXT,
    is_private INTEGER NOT NULL,
    is_verified INTEGER NOT NULL,
    is_business INTEGER NOT NULL,
    follower_count INTEGER,
    following_count INTEGER,
    media_count INTEGER,
    profile_pic_url TEXT,
    scraped_at TEXT NOT NULL,
    category TEXT,
    secondary_category TEXT,
    confidence REAL,
    reasoning TEXT,
    classified_at TEXT
);

CREATE TABLE IF NOT EXISTS posts (
    shortcode TEXT NOT NULL,
    username TEXT NOT NULL REFERENCES influencers(username),
    caption TEXT,
    hashtags TEXT NOT NULL,
    mentions TEXT NOT NULL,
    like_count INTEGER,
    comment_count INTEGER,
    timestamp TEXT,
    permalink TEXT,
    PRIMARY KEY (username, shortcode)
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    return conn


def save_collected(conn: sqlite3.Connection, collected: CollectedInfluencer) -> None:
    """Upsert a profile and replace its stored posts with the freshly scraped set.

    An upsert, not an insert: re-running `collect` on an already-classified
    account refreshes its posts without touching its category columns, so a
    classification survives a re-scrape.
    """
    profile = collected.profile
    with conn:
        conn.execute(
            """INSERT INTO influencers (
                username, user_id, full_name, biography, external_url,
                is_private, is_verified, is_business, follower_count,
                following_count, media_count, profile_pic_url, scraped_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                user_id=excluded.user_id, full_name=excluded.full_name,
                biography=excluded.biography, external_url=excluded.external_url,
                is_private=excluded.is_private, is_verified=excluded.is_verified,
                is_business=excluded.is_business, follower_count=excluded.follower_count,
                following_count=excluded.following_count, media_count=excluded.media_count,
                profile_pic_url=excluded.profile_pic_url, scraped_at=excluded.scraped_at
            """,
            (
                profile.username,
                profile.user_id,
                profile.full_name,
                profile.biography,
                str(profile.external_url) if profile.external_url else None,
                int(profile.is_private),
                int(profile.is_verified),
                int(profile.is_business),
                profile.follower_count,
                profile.following_count,
                profile.media_count,
                str(profile.profile_pic_url) if profile.profile_pic_url else None,
                datetime.now(UTC).isoformat(),
            ),
        )
        conn.execute("DELETE FROM posts WHERE username = ?", (profile.username,))
        conn.executemany(
            """INSERT INTO posts (
                shortcode, username, caption, hashtags, mentions,
                like_count, comment_count, timestamp, permalink
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    post.shortcode or post.id,
                    profile.username,
                    post.caption,
                    json.dumps(post.hashtags),
                    json.dumps(post.mentions),
                    post.like_count,
                    post.comment_count,
                    post.timestamp.isoformat(),
                    post.permalink,
                )
                for post in collected.posts
            ],
        )


def save_classification(conn: sqlite3.Connection, username: str, result: ClassificationResult) -> None:
    with conn:
        conn.execute(
            """UPDATE influencers
               SET category=?, secondary_category=?, confidence=?, reasoning=?, classified_at=?
               WHERE username=?""",
            (
                result.category.value,
                result.secondary_category.value if result.secondary_category else None,
                result.confidence,
                result.reasoning,
                datetime.now(UTC).isoformat(),
                username,
            ),
        )


def unclassified_usernames(conn: sqlite3.Connection, limit: int | None = None) -> list[str]:
    query = "SELECT username FROM influencers WHERE category IS NULL"
    if limit:
        query += " LIMIT ?"
        return [row["username"] for row in conn.execute(query, (limit,))]
    return [row["username"] for row in conn.execute(query)]


def load_features(conn: sqlite3.Connection, username: str) -> InfluencerFeatures:
    """Rebuild a classification input straight from stored rows.

    This is the only place classification input is assembled — whether the
    caller just ran `collect` or is reclassifying a week-old profile, it goes
    through the same database round-trip.
    """
    row = conn.execute("SELECT * FROM influencers WHERE username = ?", (username,)).fetchone()
    post_rows = conn.execute(
        "SELECT caption, hashtags FROM posts WHERE username = ?", (username,)
    ).fetchall()
    return InfluencerFeatures(
        username=row["username"],
        full_name=row["full_name"],
        biography=row["biography"],
        external_url=row["external_url"],
        follower_count=row["follower_count"],
        is_verified=bool(row["is_verified"]),
        is_business=bool(row["is_business"]),
        top_hashtags=rank_hashtags(json.loads(r["hashtags"]) for r in post_rows),
        sample_captions=truncate_captions(r["caption"] for r in post_rows),
    )


def fetch_all(conn: sqlite3.Connection, category: str | None = None) -> list[sqlite3.Row]:
    if category:
        return conn.execute(
            "SELECT * FROM influencers WHERE category = ? ORDER BY follower_count DESC", (category,)
        ).fetchall()
    return conn.execute("SELECT * FROM influencers ORDER BY follower_count DESC").fetchall()


def top_mentions(conn: sqlite3.Connection, min_count: int = 2, limit: int = 50) -> list[tuple[str, int]]:
    """Usernames mentioned across stored posts, excluding already-collected accounts.

    This is the PoC's discovery mechanism: osmos_core has no search/explore
    endpoint, so new candidate accounts surface from who the accounts already
    collected are tagging and shouting out, not from a hashtag search.
    """
    known = {row["username"] for row in conn.execute("SELECT username FROM influencers")}
    counts: dict[str, int] = {}
    for row in conn.execute("SELECT mentions FROM posts"):
        for mention in json.loads(row["mentions"]):
            if mention not in known:
                counts[mention] = counts.get(mention, 0) + 1
    ranked = sorted(((u, c) for u, c in counts.items() if c >= min_count), key=lambda kv: -kv[1])
    return ranked[:limit]

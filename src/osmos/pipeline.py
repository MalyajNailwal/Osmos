"""End-to-end orchestration: collect -> classify, wired through the database.

Each step reads and writes the database rather than passing objects between
steps in memory. See storage.py's module docstring for why.
"""

from __future__ import annotations

import logging
import sqlite3

from . import storage
from .classifier import classify_many
from .collector import collect_many
from .config import settings

logger = logging.getLogger(__name__)


async def run_collect(
    conn: sqlite3.Connection, usernames: list[str], posts_limit: int | None = None
) -> int:
    collected = await collect_many(
        usernames,
        posts_limit=posts_limit or settings.posts_per_profile,
        concurrency=settings.scrape_concurrency,
    )
    for item in collected:
        storage.save_collected(conn, item)
    logger.info("collected %d/%d profiles", len(collected), len(usernames))
    return len(collected)


async def run_classify(conn: sqlite3.Connection, limit: int | None = None) -> int:
    usernames = storage.unclassified_usernames(conn, limit=limit)
    if not usernames:
        return 0

    features = [storage.load_features(conn, username) for username in usernames]
    results = await classify_many(features)

    classified = 0
    for username, result in results.items():
        if result is not None:
            storage.save_classification(conn, username, result)
            classified += 1
    logger.info("classified %d/%d profiles", classified, len(usernames))
    return classified

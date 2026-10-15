"""Fetch profile + recent post metadata only — osmos_core, or a real login.

No media is ever downloaded here — classification only needs text (bio,
captions, hashtags), so this deliberately never touches osmos_core's
downloader. `collect_many()` talks to `InstagramClient` directly by default
(osmos_core's own transport ladder — anonymous tier, cookie tier if
`COOKIES_PATH` is set), but delegates to `aiograpi_collector` instead when
`INSTAGRAM_USERNAME`/`PASSWORD` are configured — a genuine logged-in session
is a stronger auth signal than any of osmos_core's tiers (see README's
"Auth" section for why).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from osmos_core.api.client import InstagramClient
from osmos_core.errors import NotFoundError, PrivateAccountError, ScraperError
from osmos_core.models.config import ScraperConfig, TransportConfig
from osmos_core.models.media import Media
from osmos_core.models.profile import Profile

from .config import settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CollectedInfluencer:
    """One profile plus the recent posts scraped for it, exactly as osmos_core returned them."""

    profile: Profile
    posts: list[Media]


def build_client() -> InstagramClient:
    config = ScraperConfig(
        cookies_path=settings.cookies_path,
        transport=TransportConfig(proxy=settings.proxy_url),
    )
    return InstagramClient.build(config)


async def collect_one(
    client: InstagramClient, username: str, posts_limit: int
) -> CollectedInfluencer | None:
    """Fetch one profile and its recent posts.

    Returns ``None`` (logging why) on a per-account failure rather than
    raising — one dead or private account should never abort a batch of 50.
    """
    try:
        profile = await client.get_profile(username)
        posts = [media async for media in client.iter_posts(username, max_items=posts_limit)]
    except (NotFoundError, PrivateAccountError) as exc:
        logger.warning("skipping %s: %s", username, exc)
        return None
    except ScraperError as exc:
        logger.warning("failed to collect %s: %s", username, exc)
        return None
    return CollectedInfluencer(profile=profile, posts=posts)


async def collect_many(
    usernames: list[str], posts_limit: int, concurrency: int
) -> list[CollectedInfluencer]:
    """Collect a batch of usernames over one shared client, bounded by `concurrency`.

    One client instance is reused across the batch: osmos_core's transport
    ladder already paces requests with its own adaptive rate limiter, so
    sharing it is what lets that pacing see the whole batch rather than each
    account resetting it.

    When INSTAGRAM_USERNAME/PASSWORD are configured, this delegates to the
    real-login path (`aiograpi_collector`) instead — a genuine logged-in
    session is a stronger signal to Instagram than osmos-core's pasted-cookie
    tiers (imported lazily to avoid a circular import, since that module
    imports `CollectedInfluencer` from here).
    """
    if settings.instagram_username and settings.instagram_password:
        from .aiograpi_collector import collect_many as aiograpi_collect_many

        return await aiograpi_collect_many(usernames, posts_limit, concurrency)

    semaphore = asyncio.Semaphore(concurrency)
    results: list[CollectedInfluencer] = []

    async with build_client() as client:

        async def _bounded(username: str) -> None:
            async with semaphore:
                collected = await collect_one(client, username, posts_limit)
                if collected is not None:
                    results.append(collected)

        await asyncio.gather(*(_bounded(u) for u in usernames))

    return results

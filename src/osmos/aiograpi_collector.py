"""Real-login collection path, used when INSTAGRAM_USERNAME/PASSWORD are set.

osmos-core's own transport ladder tops out at pasted-cookie auth, which
Instagram treats as a markedly weaker signal than a genuine `accounts/login/`
session — confirmed live on 2026-10-15: switching to a fresh residential
proxy IP made no difference to a `require_login` block, but instagrapi's own
source shows that error is routine noise its real login flow just retries
past (see `aiograpi.exceptions.PleaseWaitFewMinutes`). This module uses
`aiograpi` (an actively-maintained async instagrapi fork, MIT-licensed,
already a reference repo for this project) for the actual login and private
API, rather than hand-rolling a login/device-registration flow.

Output is mapped into the exact same `CollectedInfluencer`/`Profile`/`Media`
shapes osmos_core produces, so nothing downstream (features.py, storage.py)
needs to know which backend collected a profile.
"""

from __future__ import annotations

import asyncio
import logging

from aiograpi import Client
from aiograpi.exceptions import ClientError, UserNotFound
from aiograpi.types import Media as AiograpiMedia
from aiograpi.types import User as AiograpiUser
from osmos_core.models.media import Media, MediaType
from osmos_core.models.profile import Profile

from .collector import CollectedInfluencer
from .config import settings

logger = logging.getLogger(__name__)

_MEDIA_TYPE_BY_CODE = {1: MediaType.IMAGE, 2: MediaType.VIDEO, 8: MediaType.CAROUSEL}


async def build_aiograpi_client() -> Client:
    """Log in (or resume a persisted session) and return a ready client.

    `login()` validates an existing session before reusing it and only hits
    the network login flow when the saved one is missing or rejected, so
    this is cheap to call once per run.
    """
    client = Client(proxy=settings.proxy_url)
    session_path = settings.ig_session_path
    if session_path.exists():
        client.load_settings(session_path)
    await client.login(
        settings.instagram_username,
        settings.instagram_password,
        verification_code=settings.instagram_verification_code or "",
    )
    client.dump_settings(session_path)
    return client


def _profile_from_user(user: AiograpiUser) -> Profile:
    return Profile(
        user_id=user.pk,
        username=user.username,
        full_name=user.full_name,
        biography=user.biography,
        external_url=user.external_url or None,
        is_private=user.is_private,
        is_verified=user.is_verified,
        is_business=user.is_business,
        follower_count=user.follower_count,
        following_count=user.following_count,
        media_count=user.media_count,
        profile_pic_url=user.profile_pic_url,
        profile_pic_url_hd=user.profile_pic_url_hd,
    )


def _media_from_aiograpi(item: AiograpiMedia, username: str) -> Media:
    media_type = _MEDIA_TYPE_BY_CODE.get(item.media_type, MediaType.IMAGE)
    if media_type is MediaType.VIDEO and item.product_type == "clips":
        media_type = MediaType.REEL
    return Media(
        id=item.id,
        shortcode=item.code,
        media_type=media_type,
        owner_id=str(item.user.pk),
        username=username,
        caption=item.caption_text,
        timestamp=item.taken_at,
        like_count=item.like_count,
        comment_count=item.comment_count,
        view_count=item.view_count,
    )


async def collect_one(client: Client, username: str, posts_limit: int) -> CollectedInfluencer | None:
    """Fetch one profile and its recent posts via the real-login private API."""
    try:
        user = await client.user_info_by_username(username)
        raw_posts = await client.user_medias(int(user.pk), amount=posts_limit)
    except UserNotFound as exc:
        logger.warning("skipping %s: %s", username, exc)
        return None
    except ClientError as exc:
        logger.warning("failed to collect %s: %s", username, exc)
        return None
    profile = _profile_from_user(user)
    posts = [_media_from_aiograpi(item, username) for item in raw_posts]
    return CollectedInfluencer(profile=profile, posts=posts)


async def collect_many(
    usernames: list[str], posts_limit: int, concurrency: int
) -> list[CollectedInfluencer]:
    """Collect a batch over one shared, logged-in client, bounded by `concurrency`."""
    semaphore = asyncio.Semaphore(concurrency)
    results: list[CollectedInfluencer] = []
    client = await build_aiograpi_client()

    async def _bounded(username: str) -> None:
        async with semaphore:
            collected = await collect_one(client, username, posts_limit)
            if collected is not None:
                results.append(collected)

    await asyncio.gather(*(_bounded(u) for u in usernames))
    return results

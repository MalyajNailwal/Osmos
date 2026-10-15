"""Instagram endpoint constants.

Every Instagram-specific URL, document id and header lives here. When
Instagram rotates a ``doc_id`` — which it does without notice — this is the
only file that changes.

Document ids were captured from a live logged-out session on 2026-07-31.

2026-10-15: the timeline query above stopped working entirely — every tier,
cookies or not, got a 200 with the Instagram web app's HTML shell instead of
JSON. Confirmed live that it isn't a rotated ``doc_id`` on the same endpoint:
the whole request shape moved from ``GET /graphql/query/?doc_id=...`` to
``POST /graphql/query`` with a form body (``doc_id``, ``variables``,
``fb_api_req_friendly_name``) and two extra headers. Cross-checked against
RSSHub's actively-maintained Instagram route
(github.com/DIYgod/RSSHub, lib/routes/instagram/web-api/utils.ts) and
verified directly against live Instagram with a real session before porting
the fix into ``pagination/timeline.py``.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "BASE_URL",
    "DOC_ID_TIMELINE",
    "DOC_ID_TIMELINE_FALLBACKS",
    "GRAPHQL_API_URL",
    "GRAPHQL_QUERY_URL",
    "HIGHLIGHTS_TRAY_URL",
    "MEDIA_INFO_URL",
    "POST_URL_TEMPLATE",
    "PROFILE_URL_TEMPLATE",
    "STORIES_REEL_URL",
    "TIMELINE_FRIENDLY_NAME",
    "WEB_PROFILE_INFO_URL",
    "default_headers",
]

BASE_URL: Final = "https://www.instagram.com"

#: Cursored timeline feed. POST (as of 2026-10-15 — was GET), form body, see
#: DOC_ID_TIMELINE above. The anonymous/impersonated tiers still get a hard
#: `require_login` 401 here; only the authenticated/browser tiers (a real
#: session cookie) have been confirmed working.
GRAPHQL_QUERY_URL: Final = f"{BASE_URL}/graphql/query/"

#: Modern POST GraphQL gateway, used by the app for everything else.
GRAPHQL_API_URL: Final = f"{BASE_URL}/api/graphql"

#: Username to profile record, including the numeric id.
WEB_PROFILE_INFO_URL: Final = f"{BASE_URL}/api/v1/users/web_profile_info/"

#: Server-rendered profile page, used as a resolver of last resort.
PROFILE_URL_TEMPLATE: Final = f"{BASE_URL}/{{username}}/"

#: Server-rendered post page.
POST_URL_TEMPLATE: Final = f"{BASE_URL}/p/{{shortcode}}/"

#: Full metadata for one post, keyed by numeric media id. Requires a session:
#: verified on 2026-07-31 that logged-out post pages embed no media JSON at all,
#: rendered or not, so this is the only complete single-post route left.
MEDIA_INFO_URL: Final = f"{BASE_URL}/api/v1/media/{{media_id}}/info/"

#: Stories for one user. Requires an authenticated session.
STORIES_REEL_URL: Final = f"{BASE_URL}/api/v1/feed/reels_media/"

#: Highlight tray for one user. Requires an authenticated session.
HIGHLIGHTS_TRAY_URL: Final = f"{BASE_URL}/api/v1/highlights/{{user_id}}/highlights_tray/"

#: Timeline query, POST body doc_id — PolarisProfilePostsQuery. Verified live
#: 2026-10-15 against a real session; takes `username` (not a numeric id) and
#: the nested `data`/`__relay_internal__pv__*` variables shape documented in
#: pagination/timeline.py, not the old `id`/`first`/`after` shape.
DOC_ID_TIMELINE: Final = "28570182382647478"

#: fb_api_req_friendly_name body field the new POST gateway requires alongside
#: doc_id — Instagram keys some server-side routing off this, not just doc_id.
TIMELINE_FRIENDLY_NAME: Final = "PolarisProfilePostsQuery"

#: Additional timeline document ids, tried in order when the primary stops
#: parsing. Empty by default and deliberately so: an unverified id answers 400
#: and turns one recoverable failure into four wasted tier escalations. Add an
#: id here only after observing it work against live Instagram.
DOC_ID_TIMELINE_FALLBACKS: Final = ()


def default_headers(app_id: str, user_agent: str, referer: str | None = None) -> dict[str, str]:
    """Headers Instagram's web client sends on every XHR.

    ``X-IG-App-ID`` is optional for the timeline query but required by
    ``web_profile_info``; sending it everywhere costs nothing and keeps the
    request shape consistent across tiers. ``X-Asbd-Id``/``X-IG-WWW-Claim``
    added 2026-10-15 — the POST GraphQL gateway (the timeline query's new
    request shape) wants both; harmless on every other endpoint that doesn't
    care about them.
    """
    headers = {
        "User-Agent": user_agent,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "X-IG-App-ID": app_id,
        "X-Asbd-Id": "359341",
        "X-IG-WWW-Claim": "0",
        "X-Requested-With": "XMLHttpRequest",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Origin": BASE_URL,
    }
    if referer:
        headers["Referer"] = referer
    return headers

"""Parsing usernames from free-form text — a pasted list, a file's contents, either shape.

One function, used by both the CLI (file content or a raw comma list) and the
web UI (a textarea's raw text) — same cleaning rules either way: strip `@`,
drop blank lines and `#` comments, dedupe while preserving order.
"""

from __future__ import annotations


def parse_usernames(text: str) -> list[str]:
    seen: dict[str, None] = {}  # dict, not set — preserves first-seen order
    for line in text.replace(",", "\n").splitlines():
        name = line.strip().lstrip("@")
        if name and not name.startswith("#"):
            seen[name] = None
    return list(seen)

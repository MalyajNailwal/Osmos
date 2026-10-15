"""Runtime configuration, loaded from environment variables and .env.

One Settings object, read once at import time — every module that needs a
tunable imports `settings` rather than re-reading the environment itself.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", validate_assignment=True
    )

    @field_validator(
        "openrouter_api_key",
        "cookies_path",
        "proxy_url",
        "instagram_username",
        "instagram_password",
        "instagram_verification_code",
        mode="before",
    )
    @classmethod
    def _blank_env_value_means_unset(cls, value: object) -> object:
        """An empty .env value (`PROXY_URL=`) is "unset", not the literal empty string.

        pydantic-settings reads a present-but-empty env var as `""`, not the
        field's `None` default — for `cookies_path` that would silently
        coerce to `Path('.')` rather than staying unset. Runs before type
        coercion, so this also protects Path fields from that trap.
        """
        return value or None

    openrouter_api_key: str | None = Field(
        default=None,
        description="Required for classification. Get one at https://openrouter.ai/keys.",
    )
    classifier_model: str = Field(
        default="dots-studio/dots-3-note-preview:free",
        description="An OpenRouter model slug. Free slugs end in ':free' and rotate over "
        "time — if this one stops working, pick a replacement from "
        "https://openrouter.ai/models?max_price=0.",
    )
    classifier_concurrency: int = Field(default=5, ge=1)

    db_path: Path = Path("osmos.db")
    posts_per_profile: int = Field(default=12, ge=1, le=50)
    cookies_path: Path | None = None
    proxy_url: str | None = Field(
        default=None,
        description="e.g. http://user:pass@host:8080 — the real fix when Instagram IP-blocks "
        "the anonymous tier ('please wait a few minutes' / require_login). Needs a paid, "
        "non-shared proxy; free/shared ones get blocked the same way.",
    )
    scrape_concurrency: int = Field(default=3, ge=1)

    instagram_username: str | None = Field(
        default=None,
        description="Optional: real Instagram login (via aiograpi's private API) instead of "
        "pasted cookies. Stronger auth signal than osmos-core's cookie tiers — use a "
        "disposable account, never your main one; automated login carries real "
        "challenge/ban risk. Needs INSTAGRAM_PASSWORD too.",
    )
    instagram_password: str | None = None
    instagram_verification_code: str | None = Field(
        default=None,
        description="One-time 2FA/email code from Instagram's login challenge. Only needed "
        "for the first login with a new account; the session is cached after that.",
    )
    ig_session_path: Path = Path("ig_session.json")


settings = Settings()

_ENV_FILE = Path(".env")


def update_settings(**fields: str | None) -> None:
    """Apply settings changes from the web UI: update the live object, persist to .env.

    A ``None`` or empty value means "leave this field alone" — the web form
    only ever sends what the user actually typed into a field, so an empty
    API-key input must not overwrite an already-configured key.
    """
    updates: dict[str, str] = {}
    for field, value in fields.items():
        if not value:
            continue
        setattr(settings, field, value)  # validate_assignment=True coerces types (e.g. str -> Path)
        updates[field.upper()] = value
    if updates:
        _write_env(updates)


def _write_env(updates: dict[str, str]) -> None:
    """Merge key=value pairs into .env, preserving every other line untouched."""
    example = Path(".env.example")
    if _ENV_FILE.exists():
        lines = _ENV_FILE.read_text().splitlines()
    elif example.exists():
        lines = example.read_text().splitlines()
    else:
        lines = []

    remaining = dict(updates)
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                new_lines.append(f"{key}={remaining.pop(key)}")
                continue
        new_lines.append(line)
    new_lines.extend(f"{key}={value}" for key, value in remaining.items())
    _ENV_FILE.write_text("\n".join(new_lines) + "\n")

from __future__ import annotations

from osmos.config import Settings


def test_blank_env_values_are_treated_as_unset(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PROXY_URL", "")
    monkeypatch.setenv("COOKIES_PATH", "")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.chdir(tmp_path)  # no real .env file to load alongside the env vars

    settings = Settings()

    assert settings.proxy_url is None
    assert settings.cookies_path is None
    assert settings.openrouter_api_key is None


def test_real_values_still_pass_through(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PROXY_URL", "http://example:8080")
    monkeypatch.chdir(tmp_path)

    settings = Settings()

    assert settings.proxy_url == "http://example:8080"

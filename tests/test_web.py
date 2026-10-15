from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from osmos_core.models.media import Media, MediaType
from osmos_core.models.profile import Profile

from osmos import config, storage
from osmos.collector import CollectedInfluencer
from osmos.web import app


def test_index_page_serves_html() -> None:
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "osmos" in resp.text


def test_status_endpoint_reflects_settings(monkeypatch) -> None:
    monkeypatch.setattr(config.settings, "openrouter_api_key", "test-key")
    client = TestClient(app)
    data = client.get("/api/status").json()
    assert data["has_api_key"] is True


def test_settings_update_persists_to_env_and_live_object(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / ".env"
    monkeypatch.setattr(config, "_ENV_FILE", env_file)
    original_key = config.settings.openrouter_api_key
    client = TestClient(app)
    try:
        resp = client.post("/api/settings", json={"openrouter_api_key": "sk-test-123"})
        assert resp.status_code == 200
        assert resp.json()["has_api_key"] is True
        assert config.settings.openrouter_api_key == "sk-test-123"
        assert "OPENROUTER_API_KEY=sk-test-123" in env_file.read_text()
    finally:
        config.settings.openrouter_api_key = original_key


def test_profiles_endpoint_returns_stats(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(config.settings, "db_path", db_path)
    conn = storage.connect(db_path)
    profile = Profile(user_id="1", username="chefjane", biography="recipes", follower_count=100)
    media = Media(
        id="1",
        shortcode="abc",
        media_type=MediaType.IMAGE,
        owner_id="1",
        username="chefjane",
        caption="#pasta",
        timestamp=datetime.now(UTC),
    )
    storage.save_collected(conn, CollectedInfluencer(profile=profile, posts=[media]))

    client = TestClient(app)
    data = client.get("/api/profiles").json()
    assert data["total"] == 1
    assert data["rows"][0]["username"] == "chefjane"


def test_collect_rejects_empty_username_list() -> None:
    client = TestClient(app)
    resp = client.post("/api/run", json={"usernames": [], "posts": 5})
    assert resp.status_code == 400

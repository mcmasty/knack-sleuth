"""Tests for environment and dotenv configuration."""

from knack_sleuth.config import Settings


def test_unrelated_dotenv_variables_are_ignored(tmp_path, monkeypatch):
    """A consumer's project .env may contain settings for many other tools."""
    (tmp_path / ".env").write_text(
        "KNACK_APP_ID=app_from_dotenv\n"
        "KNACK_CACHE_TTL_HOURS=12\n"
        "MEZMO_WEBHOOK_SECRET=not-a-knack-setting\n"
        "KNACK_APPLICATION_ID=consumer-specific-alias\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("KNACK_APP_ID", raising=False)
    monkeypatch.delenv("KNACK_CACHE_TTL_HOURS", raising=False)

    settings = Settings()

    assert settings.knack_app_id == "app_from_dotenv"
    assert settings.knack_cache_ttl_hours == 12

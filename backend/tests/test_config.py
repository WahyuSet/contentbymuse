import pytest
from pydantic import ValidationError

from app.config import Settings


def test_secret_key_is_required(monkeypatch):
    monkeypatch.delenv("APP_SECRET_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_read_env_and_defaults(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret")
    settings = Settings(_env_file=None)
    assert settings.app_secret_key == "test-secret"
    assert settings.database_url == "sqlite+aiosqlite:///./storage/app.db"
    assert settings.worker_concurrency == 6

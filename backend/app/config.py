from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Wajib: API dan worker menolak start tanpa kunci ini (Spec §10).
    app_secret_key: str = Field(min_length=1)
    database_url: str = "sqlite+aiosqlite:///./storage/app.db"
    storage_path: Path = Path("./storage")
    worker_concurrency: int = 6
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FAT_", env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg2://fat:fat@localhost:5432/fat_platform"
    signing_secret: str = "development-only-change-me"
    algorithm_version: str = "reconciliation-1.0.0"
    worker_poll_seconds: float = 1.0


@lru_cache
def get_settings() -> Settings:
    return Settings()

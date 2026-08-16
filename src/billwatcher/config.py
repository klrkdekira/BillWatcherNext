from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "development"
    site_host: str = "localhost"
    public_base_url: str = "http://localhost:8000"
    contact_email: str = "operator@example.org"
    database_url: str = "postgresql+psycopg://billwatcher:billwatcher@localhost/billwatcher"
    blob_storage_root: Path = Path("var/blobs")
    scrape_enabled: bool = False
    scrape_interval_hours: int = Field(default=12, ge=1)
    scrape_delay_seconds: float = Field(default=2.0, ge=2.0)
    scrape_concurrency: int = Field(default=1, ge=1)
    scrape_max_requests_per_run: int = 2000
    scrape_max_bytes_per_run: int = 1_073_741_824
    scrape_max_duration_seconds: int = 3600
    scrape_max_new_documents: int = Field(default=500, ge=0)
    document_max_bytes: int = 104_857_600
    absence_streak_alert: int = 3
    count_drop_abort_fraction: float = 0.30
    fetch_attempt_retention_days: int = 180
    semantic_search_enabled: bool = False
    rag_enabled: bool = False

    @model_validator(mode="after")
    def reject_production_placeholders(self) -> "Settings":
        if self.environment == "production":
            values = (self.site_host, self.public_base_url, self.contact_email, self.database_url)
            if any("example.org" in value or "CHANGE_ME" in value for value in values):
                raise ValueError("production configuration contains placeholder values")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+asyncpg://autodepth:autodepth@localhost:5432/autodepth"
    scrape_schedule: str = "15 3 * * *"
    weekly_reconciliation_schedule: str = "30 4 * * 0"
    request_log_retention_days: int = 90


settings = Settings()

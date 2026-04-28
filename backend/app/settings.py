from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+asyncpg://autodepth:autodepth@localhost:5432/autodepth"
    redis_url: str = "redis://localhost:6379/0"
    raw_page_artifact_backend: str = "local"
    raw_page_storage_dir: str = "data/raw_pages"
    scrape_schedule: str = "15 3 * * *"
    weekly_reconciliation_schedule: str = "30 4 * * 0"
    request_log_retention_days: int = 90
    bat_list_page_delay_min: float = 3.0
    bat_list_page_delay_max: float = 8.0
    bat_detail_delay_min: float = 5.0
    bat_detail_delay_max: float = 12.0
    bat_target_delay_min: float = 30.0
    bat_target_delay_max: float = 120.0
    bat_stop_on_block: bool = True
    bat_skip_enriched_details: bool = True
    bat_detail_refresh_after_days: int = 30
    cab_interaction_delay_min: float = 4.0
    cab_interaction_delay_max: float = 8.0
    cab_search_delay_min: float = 5.0
    cab_search_delay_max: float = 12.0
    cab_stop_on_block: bool = True


settings = Settings()

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+asyncpg://autodepth:autodepth@localhost:5432/autodepth"
    clerk_secret_key: str = ""
    anthropic_api_key: str = ""
    scrape_schedule: str = "0 2 * * *"


settings = Settings()

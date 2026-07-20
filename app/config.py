from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5434/campaigns"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"


settings = Settings()

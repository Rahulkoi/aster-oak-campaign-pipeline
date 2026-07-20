from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5434/campaigns"

    # "anthropic" (native tool calling) or "openai" (any OpenAI-compatible
    # endpoint: OpenAI, Groq, Gemini). The exercise hands out one of the two
    # on the day; free tiers (Groq/Gemini) work for practice.
    llm_provider: str = "anthropic"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"

    openai_api_key: str = ""
    openai_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    openai_model: str = "gemini-2.5-flash"

    # Minimum seconds between LLM calls. Free tiers have strict RPM limits;
    # pacing proactively beats burning quota on 429 retries.
    llm_min_interval_seconds: float = 0.0


settings = Settings()

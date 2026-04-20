from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str | None = None
    tavily_api_key: str | None = None
    default_model: str = "claude-haiku-4-5"
    triage_model: str = "claude-haiku-4-5"
    log_level: str = "INFO"
    research_max_iterations: int = 3


settings = Settings()

# Max simultaneous child tasks within one parent. Caps ITPM burstiness from
# Send-based fan-out; see docs/rate_limiting.md.
CHILD_CONCURRENCY = 1

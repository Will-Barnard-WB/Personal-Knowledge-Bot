"""
Application configuration — all settings loaded from environment / .env file.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Claude
    anthropic_api_key: str = ""
    claude_fast_model: str = "claude-haiku-4-5"
    claude_smart_model: str = "claude-haiku-4-5"

    # Database
    database_url: str = "postgresql+asyncpg://pkb:pkbpassword@localhost:5432/personal_knowledge_bot"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"

    # Gateway
    gateway_url: str = "http://localhost:3000"
    webhook_url: str = "http://localhost:8000/webhook"
    my_whatsapp_id: str = ""

    # Rate limiting
    rate_limit_max_requests: int = 10
    rate_limit_window_seconds: int = 60

    # Whisper
    whisper_model: str = "base"

    # ARQ Worker
    arq_max_jobs: int = 5


@lru_cache
def get_settings() -> Settings:
    """Singleton settings instance — cached after first call."""
    return Settings()

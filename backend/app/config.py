from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Все настройки читаются из переменных окружения (или .env)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./tender_filter.db"
    # Без Redis задачи выполняются в фоне внутри процесса API.
    redis_url: str | None = None

    # ЕГРЮЛ: mock (демо-данные) или dadata (нужен ключ).
    egrul_provider: str = "mock"
    dadata_api_key: str | None = None
    egrul_cache_hours: int = 24

    # LLM: ollama, openai (любой OpenAI-совместимый API) или none (только правила).
    llm_provider: str = "none"
    ollama_url: str = "http://ollama:11434"
    llm_model: str = "qwen2.5:1.5b"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str | None = None
    llm_timeout_seconds: float = 90.0

    embedding_dim: int = 512
    seed_demo_data: bool = True
    max_upload_mb: int = 100
    cors_origins: str = "*"


@lru_cache
def get_settings() -> Settings:
    return Settings()

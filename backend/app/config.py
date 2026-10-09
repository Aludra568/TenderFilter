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
    # Открытые сервисы ФНС (egrul.nalog.ru + rmsp.nalog.ru) без ключа — для любого ИНН вне демо-данных.
    egrul_public_fns: bool = True
    egrul_timeout_seconds: float = 3.5  # общий бюджет на поиск одной организации в ФНС

    # LLM: ollama, openai (любой OpenAI-совместимый API) или none (только правила).
    llm_provider: str = "none"
    ollama_url: str = "http://ollama:11434"
    llm_model: str = "qwen2.5:1.5b"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str | None = None
    llm_timeout_seconds: float = 90.0
    # Сколько ждать LLM при разборе критериев в «быстрой оценке», чтобы уложиться в 10 с из ТЗ.
    llm_parse_timeout_seconds: float = 5.0
    # Второе мнение LLM по оценке алгоритма: не меняет процент, спорное отправляет на ручную проверку
    llm_review: bool = True
    llm_review_timeout_seconds: float = 3.0
    # Официальный API ЕИС для физлиц (getDocsIP). Токен выдаётся в ЛК ЕИС через Госуслуги.
    eis_token: str = ""
    eis_getdocs_url: str = "https://int44.zakupki.gov.ru/eis-integration/services/getDocsIP"

    embedding_dim: int = 512
    seed_demo_data: bool = True
    max_upload_mb: int = 100
    cors_origins: str = "*"


@lru_cache
def get_settings() -> Settings:
    return Settings()

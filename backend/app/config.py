from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "InferLog AI"
    environment: str = "development"
    database_url: str = "sqlite:///./data/inferlog.db"
    ingestion_url: str = "http://127.0.0.1:8000/api/ingest/inference"
    ingestion_queue_size: int = 2000
    context_window_messages: int = 8
    input_preview_chars: int = 320
    output_preview_chars: int = 320
    default_provider: str = "openai"
    default_model: str = "gpt-4.1-mini"
    request_timeout_seconds: float = 90.0
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()

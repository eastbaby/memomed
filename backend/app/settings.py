import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True
    )
    
    LLM_API_KEY: str
    LLM_BASE_URL: str
    LLM_MODEL: str
    SFT_MODEL: str = "SFT_MODEL"
    EMBEDDING_MODEL: str
    LANGSMITH_API_KEY: str
    LANGSMITH_TRACING: str = "true"
    LANGSMITH_PROJECT: str = "memomed-agent-dev"
    LANGSMITH_ENDPOINT: str = "https://api.smith.langchain.com"
    POSTGRES_URI_CUSTOM: str


settings = Settings()


def configure_langsmith_environment() -> None:
    """Expose LangSmith settings to LangChain/LangGraph tracing runtime."""
    os.environ.setdefault("LANGSMITH_TRACING", settings.LANGSMITH_TRACING)
    os.environ.setdefault("LANGSMITH_API_KEY", settings.LANGSMITH_API_KEY)
    os.environ.setdefault("LANGSMITH_PROJECT", settings.LANGSMITH_PROJECT)
    os.environ.setdefault("LANGSMITH_ENDPOINT", settings.LANGSMITH_ENDPOINT)


configure_langsmith_environment()

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
    LANGSMITH_API_KEY: str
    LANGSMITH_TRACING: str = "true"


settings = Settings()
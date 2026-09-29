from pydantic_settings import BaseSettings
from functools import lru_cache
from pathlib import Path

from pydantic import ConfigDict, Field, SecretStr

class Settings(BaseSettings):
    model_config = ConfigDict(
        env_file = ".env",
        env_file_encoding = "utf-8",
        extra = "ignore"
    )

    model_id: str = "google/gemini-3.8-flash"
    vision_model_id: str | None = None
    openai_api_key: SecretStr | None = None
    memory_dir: Path | None = Field(
        default=None,
        validation_alias="DEEP_WEB_AGENT_MEMORY_DIR",
    )


@lru_cache(1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

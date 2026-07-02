from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Optional, Union

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql://agent:agent@localhost:5432/agentia"
    openai_api_key: str = ""
    openai_base_url: Optional[str] = None
    openai_router_model: str = "gpt-4.1-mini"
    openai_chat_model: str = "moonshotai/kimi-k2"
    admin_api_token: str = ""
    chat_max_context_chunks: int = 6
    chat_rate_limit_per_minute: int = 10
    site_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("site_allowed_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: Union[str, list[str]]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [str(origin).strip() for origin in self.site_allowed_origins if str(origin).strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

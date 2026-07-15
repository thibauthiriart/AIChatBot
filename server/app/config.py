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
    openai_chat_model: str = "moonshotai/kimi-k2.5"
    admin_api_token: str = ""
    noota_ingest_token: str = ""
    default_scope_name: str = "Base documentaire principale"
    default_scope_base_url: str = "https://assistant.local"
    noota_google_drive_root_folder_id: str = ""
    noota_google_drive_scan_limit: int = 100
    widget_enabled: bool = True
    chat_service_enabled: bool = True
    chat_max_context_chunks: int = 6
    chat_rate_limit_per_minute: int = 10
    booking_provider: str = "google_calendar"
    booking_timezone_default: str = "Europe/Paris"
    booking_slot_duration_minutes: int = 30
    booking_max_suggestions: int = 3
    booking_workday_start_hour: int = 9
    booking_workday_end_hour: int = 17
    booking_event_summary: str = "Premier rendez-vous"
    google_calendar_id: str = ""
    google_service_account_file: str = ""
    google_service_account_subject: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_from_name: str = "Assistant de gestion"
    smtp_use_starttls: bool = True
    smtp_use_ssl: bool = False
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

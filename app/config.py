"""Application configuration module."""

from functools import lru_cache
from pathlib import Path
from typing import List, Union

from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """CiteVerify backend environment settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    APP_NAME: str = "CiteVerify"
    APP_ENV: str = "development"
    DEBUG: bool = True
    API_V1_STR: str = "/api"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    CORS_ORIGINS: Union[List[str], str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, (list, str)):
            return v  # handled by pydantic json decoder if string represents list
        return []

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./storage/citeverify.db"

    # Storage paths
    UPLOAD_DIR: Path = Path("./storage/uploads")
    EXTRACTED_DIR: Path = Path("./storage/extracted")
    REPORTS_DIR: Path = Path("./storage/reports")

    # External APIs
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-1.5-pro"

    # Rate limiting
    EXTERNAL_API_RATE_LIMIT: int = 30  # requests per minute


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()


"""Application configuration module."""

from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Union
from dotenv import load_dotenv

# Ensure local .env overrides host system environment variables (e.g. stale dummy keys)
load_dotenv(".env", override=True)

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

    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://sweet-gumdrop-378fba.netlify.app",
    ]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            v_clean = v.strip()
            if v_clean.startswith("[") and v_clean.endswith("]"):
                import json
                try:
                    parsed = json.loads(v_clean)
                    if isinstance(parsed, list):
                        return [str(i).strip().rstrip("/") for i in parsed if str(i).strip()]
                except Exception:
                    pass
            return [i.strip().rstrip("/") for i in v_clean.split(",") if i.strip()]
        elif isinstance(v, list):
            return [str(i).strip().rstrip("/") for i in v if str(i).strip()]
        return []

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./storage/citeverify.db"

    # Storage paths
    UPLOAD_DIR: Path = Path("./storage/uploads")
    EXTRACTED_DIR: Path = Path("./storage/extracted")
    REPORTS_DIR: Path = Path("./storage/reports")

    # External APIs
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"
    OPENALEX_API_KEY: Optional[str] = None
    CROSSREF_MAILTO: str = "citeverify@example.com"

    # Rate limiting
    EXTERNAL_API_RATE_LIMIT: int = 30  # requests per minute


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()


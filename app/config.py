from __future__ import annotations

import os
from dataclasses import dataclass


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return float(value)


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _database_url() -> str:
    value = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://hackathons:hackathons@localhost:5432/hackathons",
    )
    if value.startswith("postgres://"):
        return value.replace("postgres://", "postgresql+asyncpg://", 1)
    if value.startswith("postgresql://"):
        return value.replace("postgresql://", "postgresql+asyncpg://", 1)
    return value


@dataclass(frozen=True)
class Settings:
    database_url: str = _database_url()
    devpost_search_url: str = os.getenv(
        "DEVPOST_SEARCH_URL",
        "https://devpost.com/software/search?page=1&query=is%3Awinner+has%3Avideo&source=suggestion",
    )
    max_projects: int = _int_env("MAX_PROJECTS", 25)
    scraper_delay_seconds: float = _float_env("SCRAPER_DELAY_SECONDS", 1.5)
    chromium_path: str = os.getenv("CHROMIUM_PATH", "/usr/bin/chromium")
    chromium_headless: bool = _bool_env("CHROMIUM_HEADLESS", True)
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    llm_provider: str = os.getenv("LLM_PROVIDER", "auto").lower()


settings = Settings()

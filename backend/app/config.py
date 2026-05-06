from __future__ import annotations
from typing import List
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    database_url: str = "sqlite+aiosqlite:///./sheska.db"
    source_store_path: str = "./source-store"
    wiki_store_path: str = "./wiki-store"
    prompts_path: str = "./prompts"

    litellm_provider: str = "anthropic"
    litellm_model: str = "claude-haiku-4-5-20251001"
    litellm_api_key: str = ""
    litellm_base_url: str = ""

    allowed_extensions: List[str] = ["pdf", "txt", "md"]

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()

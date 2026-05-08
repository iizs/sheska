from __future__ import annotations
import json
from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings
from functools import lru_cache

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
for _candidate in (BACKEND_ROOT.parent / ".env", BACKEND_ROOT / ".env"):
    if _candidate.exists():
        ENV_FILE = _candidate
        break
else:
    ENV_FILE = BACKEND_ROOT / ".env"


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
    source_base_url: str = ""

    signup_enabled: bool = True
    password_min_length: int = 8

    # CORS — accept raw string from .env to avoid pydantic_settings auto JSON-decode
    # of complex types (List). Use `cors_origins` property to get the parsed list.
    # Format: comma-separated origins, or a JSON-encoded list. Wildcard "*" disallowed in prod.
    allowed_origins: str = "http://localhost:3000"

    @property
    def cors_origins(self) -> List[str]:
        raw = (self.allowed_origins or "").strip()
        if not raw:
            return ["http://localhost:3000"]
        if raw.startswith("["):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [str(x) for x in parsed]
            except json.JSONDecodeError:
                pass
        return [item.strip() for item in raw.split(",") if item.strip()]

    class Config:
        env_file = str(ENV_FILE) if ENV_FILE.exists() else ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()

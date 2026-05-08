from __future__ import annotations
import textwrap
from pathlib import Path
import pytest
from app.config import Settings


def test_cors_origins_default_includes_localhost():
    s = Settings()
    assert "http://localhost:3000" in s.cors_origins


def test_cors_origins_parses_comma_string():
    s = Settings(allowed_origins="http://localhost:3000,http://192.168.50.106:3000")
    assert s.cors_origins == [
        "http://localhost:3000",
        "http://192.168.50.106:3000",
    ]


def test_cors_origins_parses_json_list_string():
    s = Settings(allowed_origins='["http://a.example", "http://b.example"]')
    assert s.cors_origins == ["http://a.example", "http://b.example"]


def test_cors_origins_strips_whitespace():
    s = Settings(allowed_origins=" http://x.example , http://y.example ")
    assert s.cors_origins == ["http://x.example", "http://y.example"]


def test_cors_origins_empty_string_falls_back_to_default():
    s = Settings(allowed_origins="")
    assert s.cors_origins == ["http://localhost:3000"]


def test_cors_origins_skips_empty_segments():
    s = Settings(allowed_origins="http://a.example,,http://b.example")
    assert s.cors_origins == ["http://a.example", "http://b.example"]


def test_cors_origins_loads_from_env_file_without_settings_error(tmp_path: Path, monkeypatch):
    """Regression: pydantic_settings v2 raised SettingsError on List[str] from .env.

    Storing the field as `str` and parsing via property avoids the auto-JSON decode.
    """
    env_path = tmp_path / ".env"
    env_path.write_text(textwrap.dedent("""\
        ALLOWED_ORIGINS=http://localhost:3000,http://192.168.50.106:3000
    """))

    # Override env_file path via Settings.Config
    class _CfgSettings(Settings):
        class Config:
            env_file = str(env_path)

    s = _CfgSettings()
    assert s.cors_origins == [
        "http://localhost:3000",
        "http://192.168.50.106:3000",
    ]


def test_cors_origins_loads_json_from_env_file(tmp_path: Path):
    """JSON list form from .env also works."""
    env_path = tmp_path / ".env"
    env_path.write_text('ALLOWED_ORIGINS=["http://a.example","http://b.example"]\n')

    class _CfgSettings(Settings):
        class Config:
            env_file = str(env_path)

    s = _CfgSettings()
    assert s.cors_origins == ["http://a.example", "http://b.example"]

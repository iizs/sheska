from __future__ import annotations
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


def test_cors_origins_loads_from_environ_without_settings_error(monkeypatch):
    """Regression: pydantic_settings v2.6 raised SettingsError on List[str] from env.

    Storing the field as `str` and parsing via property avoids the auto-JSON decode.
    """
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000,http://192.168.50.106:3000")
    s = Settings()
    assert s.cors_origins == [
        "http://localhost:3000",
        "http://192.168.50.106:3000",
    ]


def test_cors_origins_loads_json_from_environ(monkeypatch):
    """JSON list form via env var also works (no SettingsError)."""
    monkeypatch.setenv("ALLOWED_ORIGINS", '["http://a.example","http://b.example"]')
    s = Settings()
    assert s.cors_origins == ["http://a.example", "http://b.example"]

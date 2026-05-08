from __future__ import annotations
from unittest.mock import patch
import pytest
from app.config import Settings


def test_allowed_origins_default_includes_localhost():
    s = Settings()
    assert "http://localhost:3000" in s.allowed_origins


def test_allowed_origins_parses_comma_string():
    s = Settings(allowed_origins="http://localhost:3000,http://192.168.50.106:3000")
    assert "http://localhost:3000" in s.allowed_origins
    assert "http://192.168.50.106:3000" in s.allowed_origins


def test_allowed_origins_parses_json_list_string():
    s = Settings(allowed_origins='["http://a.example", "http://b.example"]')
    assert s.allowed_origins == ["http://a.example", "http://b.example"]


def test_allowed_origins_strips_whitespace():
    s = Settings(allowed_origins=" http://x.example , http://y.example ")
    assert s.allowed_origins == ["http://x.example", "http://y.example"]


def test_allowed_origins_empty_string_falls_back_to_default():
    s = Settings(allowed_origins="")
    assert s.allowed_origins == ["http://localhost:3000"]


def test_allowed_origins_skips_empty_segments():
    s = Settings(allowed_origins="http://a.example,,http://b.example")
    assert s.allowed_origins == ["http://a.example", "http://b.example"]

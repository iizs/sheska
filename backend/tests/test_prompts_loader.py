from __future__ import annotations
import pytest
from pathlib import Path
from unittest.mock import patch

from app.config import resolve_path


def test_resolve_path_absolute_returns_as_is(tmp_path):
    abs_path = tmp_path / "some-dir"
    out = resolve_path(str(abs_path))
    assert out == abs_path


def test_resolve_path_finds_existing_under_project_root(tmp_path):
    """Relative path resolves to first existing candidate (use unique name to avoid autouse conflict)."""
    target = tmp_path / "fake-prompts"
    target.mkdir()
    (target / "ingest.txt").write_text("x")

    with patch("app.config.PROJECT_ROOT", tmp_path), \
         patch("app.config.BACKEND_ROOT", tmp_path / "backend"):
        out = resolve_path("./fake-prompts")
        assert out == target.resolve()


def test_load_prompt_raises_on_missing_file(tmp_path):
    """SC: silent empty-string return is gone — raises FileNotFoundError."""
    from app.services.pipeline import _load_prompt

    bogus = tmp_path / "nonexistent"
    with patch("app.services.pipeline.get_settings") as mock_settings:
        s = mock_settings.return_value
        s.prompts_path = str(bogus)
        with pytest.raises(FileNotFoundError, match="Prompt file not found"):
            _load_prompt("ingest")


def test_load_prompt_raises_on_empty_file(tmp_path):
    """Empty prompt file is treated as a configuration bug."""
    from app.services.pipeline import _load_prompt

    prompts = tmp_path / "empty-prompts"
    prompts.mkdir()
    (prompts / "ingest.txt").write_text("   \n  \n")  # whitespace only

    with patch("app.services.pipeline.get_settings") as mock_settings:
        s = mock_settings.return_value
        s.prompts_path = str(prompts)
        with pytest.raises(ValueError, match="Prompt file is empty"):
            _load_prompt("ingest")


def test_load_prompt_resolves_relative_path_via_project_root(tmp_path):
    """Relative prompts_path that lives under PROJECT_ROOT (not backend cwd) loads correctly."""
    from app.services import pipeline

    fake_root = tmp_path / "fakeproject"
    (fake_root / "backend").mkdir(parents=True)
    prompts = fake_root / "prompts"
    prompts.mkdir()
    (prompts / "ingest.txt").write_text("real ingest prompt")

    with patch("app.config.PROJECT_ROOT", fake_root), \
         patch("app.config.BACKEND_ROOT", fake_root / "backend"), \
         patch("app.services.pipeline.get_settings") as mock_settings:
        s = mock_settings.return_value
        s.prompts_path = "./prompts"
        out = pipeline._load_prompt("ingest")
    assert "real ingest prompt" in out


def test_load_prompt_real_file_works():
    """End-to-end: real PROJECT_ROOT/prompts/ingest.txt is non-empty and loads."""
    from app.services.pipeline import _load_prompt

    out = _load_prompt("ingest")
    assert out
    assert "JSON" in out  # v0.3 prompts include JSON Plan instructions

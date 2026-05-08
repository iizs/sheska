from __future__ import annotations
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock
import pytest

from app.services import llm_client


def _fake_response(text: str = "{}"):
    msg = SimpleNamespace(content=text)
    choice = SimpleNamespace(message=msg)
    return SimpleNamespace(choices=[choice])


@pytest.mark.asyncio
async def test_anthropic_uses_response_format(monkeypatch):
    captured: dict = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _fake_response('{"actions": []}')

    with patch("app.services.llm_client.get_settings") as mock_settings, \
         patch("app.services.llm_client.litellm.acompletion", new=fake_acompletion):
        s = mock_settings.return_value
        s.litellm_provider = "anthropic"
        s.litellm_model = "claude-haiku-4-5"
        s.litellm_api_key = "key"
        s.litellm_base_url = ""
        await llm_client.call_llm(
            "system",
            "user",
            response_format={"type": "json_object"},
        )

    assert captured.get("response_format") == {"type": "json_object"}
    assert "format" not in captured


@pytest.mark.asyncio
async def test_ollama_skips_json_enforcement_entirely(monkeypatch):
    """Ollama: LiteLLM provider buggy — neither response_format nor format='json' work.
    Skip JSON enforcement and rely on prompt + Pydantic + graceful degrade.
    """
    captured: dict = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _fake_response('{"actions": []}')

    with patch("app.services.llm_client.get_settings") as mock_settings, \
         patch("app.services.llm_client.litellm.acompletion", new=fake_acompletion):
        s = mock_settings.return_value
        s.litellm_provider = "ollama"
        s.litellm_model = "ollama/gemma4:31b-cloud"
        s.litellm_api_key = ""
        s.litellm_base_url = "http://localhost:11434"
        await llm_client.call_llm(
            "system",
            "user",
            response_format={"type": "json_object"},
        )

    # Both flags must be absent — LiteLLM Ollama treats either as a function call signal
    assert "format" not in captured
    assert "response_format" not in captured


@pytest.mark.asyncio
async def test_ollama_chat_also_skips_json_enforcement():
    """ollama_chat (LiteLLM v1.x naming) is treated identically to 'ollama'."""
    captured: dict = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _fake_response('{"actions": []}')

    with patch("app.services.llm_client.get_settings") as mock_settings, \
         patch("app.services.llm_client.litellm.acompletion", new=fake_acompletion):
        s = mock_settings.return_value
        s.litellm_provider = "ollama_chat"
        s.litellm_model = "ollama_chat/gemma4"
        s.litellm_api_key = ""
        s.litellm_base_url = "http://localhost:11434"
        await llm_client.call_llm(
            "system",
            "user",
            response_format={"type": "json_object"},
        )

    assert "format" not in captured
    assert "response_format" not in captured


@pytest.mark.asyncio
async def test_no_json_request_passes_through_unchanged():
    """response_format=None → neither field set on either provider."""
    captured: dict = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _fake_response("plain text")

    with patch("app.services.llm_client.get_settings") as mock_settings, \
         patch("app.services.llm_client.litellm.acompletion", new=fake_acompletion):
        s = mock_settings.return_value
        s.litellm_provider = "anthropic"
        s.litellm_model = "claude-haiku-4-5"
        s.litellm_api_key = "key"
        s.litellm_base_url = ""
        await llm_client.call_llm("system", "user")

    assert "response_format" not in captured
    assert "format" not in captured

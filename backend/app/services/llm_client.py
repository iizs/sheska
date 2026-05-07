from __future__ import annotations
import litellm
from ..config import get_settings


async def call_llm(system_prompt: str, user_content: str) -> str:
    settings = get_settings()

    model = settings.litellm_model
    if "/" not in model:
        model = f"{settings.litellm_provider}/{model}"

    # Ollama / gemma 등 일부 오픈모델은 system role 지시를 거의 무시한다.
    # system 내용을 user 메시지 앞에 붙여 단일 user 메시지로 전달하면 instruction following이 크게 개선됨.
    provider = settings.litellm_provider.lower()
    weak_system_following = provider in {"ollama", "ollama_chat"}

    if weak_system_following:
        merged = (
            f"{system_prompt}\n\n"
            f"═══════════════════════════════════════════\n"
            f"SOURCE INPUT BELOW\n"
            f"═══════════════════════════════════════════\n\n"
            f"{user_content}\n\n"
            f"═══════════════════════════════════════════\n"
            f"FINAL REMINDER — YOUR RESPONSE\n"
            f"═══════════════════════════════════════════\n"
            f"Output the wiki page(s) ONLY. The very first characters of your response\n"
            f"MUST be either '=== FILE: ' (for ingest) or '---' (for edit).\n"
            f"Do NOT begin with 'This is', 'Here is', a summary, or any commentary.\n"
            f"If you start with anything other than the required marker, your response is invalid.\n"
        )
        messages = [{"role": "user", "content": merged}]
    else:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

    kwargs: dict = {
        "model": model,
        "messages": messages,
        "temperature": 0,
    }
    if settings.litellm_api_key:
        kwargs["api_key"] = settings.litellm_api_key
    if settings.litellm_base_url:
        kwargs["base_url"] = settings.litellm_base_url

    response = await litellm.acompletion(**kwargs)
    return response.choices[0].message.content

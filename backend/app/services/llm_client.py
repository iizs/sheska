from __future__ import annotations
import litellm
from ..config import get_settings


async def call_llm(system_prompt: str, user_content: str) -> str:
    settings = get_settings()

    kwargs: dict = {
        "model": f"{settings.litellm_provider}/{settings.litellm_model}",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }
    if settings.litellm_api_key:
        kwargs["api_key"] = settings.litellm_api_key
    if settings.litellm_base_url:
        kwargs["base_url"] = settings.litellm_base_url

    response = await litellm.acompletion(**kwargs)
    return response.choices[0].message.content

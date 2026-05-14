from __future__ import annotations
import asyncio
import hashlib
import json
import logging
from typing import Optional, Callable, Awaitable
import litellm
from ..config import get_settings

logger = logging.getLogger(__name__)


async def call_llm(
    system_prompt: str,
    user_content: str,
    response_format: Optional[dict] = None,
) -> str:
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
            f"INPUT BELOW\n"
            f"═══════════════════════════════════════════\n\n"
            f"{user_content}\n\n"
            f"═══════════════════════════════════════════\n"
            f"FINAL REMINDER\n"
            f"═══════════════════════════════════════════\n"
            f"Output ONLY what the system instructed. Do not begin with\n"
            f"'This is', 'Here is', a summary, or any commentary.\n"
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
    # JSON 강제 적용 정책 (ADR-0011 운영 결정):
    # - Anthropic/OpenAI 등: response_format={"type":"json_object"} 그대로 전달
    # - Ollama: LiteLLM provider 버그 — response_format / format="json" 어느 플래그라도
    #   응답을 function call 구조로 해석해 KeyError: 'arguments' 발생.
    #   → JSON 강제 자체를 사용하지 않고 prompt + Pydantic + graceful degrade에만 의존
    if response_format is not None:
        wants_json = (
            isinstance(response_format, dict)
            and response_format.get("type") == "json_object"
        )
        if weak_system_following and wants_json:
            pass  # Ollama: skip JSON enforcement entirely
        else:
            kwargs["response_format"] = response_format
    if settings.litellm_api_key:
        kwargs["api_key"] = settings.litellm_api_key
    if settings.litellm_base_url:
        kwargs["base_url"] = settings.litellm_base_url

    response = await litellm.acompletion(**kwargs)
    return response.choices[0].message.content


# =========================================================================
# v0.4 — Agentic loop (Anthropic direct, ADR-0013)
# =========================================================================


class AgenticError(Exception):
    """Raised when the agentic loop must abort. error reason in msg."""


class AgenticCancelled(Exception):
    """Raised when the loop was cancelled by user."""


def is_anthropic_provider() -> bool:
    return get_settings().litellm_provider.lower() == "anthropic"


async def run_agentic_loop(
    system_prompt: str,
    user_content: str,
    tools_schemas: list[dict],
    tool_executor: Callable[[str, dict], Awaitable[str]],
    *,
    on_step: Optional[Callable[[dict], Awaitable[None]]] = None,
    is_cancelled: Optional[Callable[[], Awaitable[bool]]] = None,
) -> dict:
    """Anthropic Messages API agentic loop with safety guards (SC-64/65/66/67).

    Args:
      system_prompt: agent's system message.
      user_content: initial user message.
      tools_schemas: Anthropic tool schemas list (from tools.list_schemas()).
      tool_executor: async callable(tool_name, tool_input) -> result_string.
      on_step: optional async callback after each tool result is produced; receives a
               step dict matching SC-67 schema. Used for DB checkpoint.
      is_cancelled: optional async callable returning True if the job should abort.

    Returns:
      {"final_text": str, "iterations": int, "tool_calls": int, "stop_reason": str}

    Raises:
      AgenticError on safety violations or context limits.
      AgenticCancelled on user cancel.
    """
    import anthropic  # local import to avoid mandatory dependency for non-Anthropic paths

    settings = get_settings()
    if settings.litellm_provider.lower() != "anthropic":
        raise AgenticError(
            f"This provider ({settings.litellm_provider}) does not support agentic mode (v0.4). "
            "Use Anthropic, or downgrade to v0.3.1 for legacy multi-provider behavior."
        )

    api_key = settings.litellm_api_key
    if not api_key:
        raise AgenticError("ANTHROPIC API key (LITELLM_API_KEY) is not set")

    model = settings.litellm_model
    # Anthropic SDK uses bare model id (no "anthropic/" prefix)
    if model.startswith("anthropic/"):
        model = model.split("/", 1)[1]

    client = anthropic.AsyncAnthropic(api_key=api_key)

    messages: list[dict] = [{"role": "user", "content": user_content}]
    iterations = 0
    tool_calls = 0
    recent_calls: list[str] = []
    stop_reason = "unknown"
    final_text = ""
    step_no = 0

    async def _maybe_cancel():
        if is_cancelled is not None and await is_cancelled():
            raise AgenticCancelled("cancelled by user")

    async def _call_anthropic():
        return await client.messages.create(
            model=model,
            max_tokens=4096,
            system=system_prompt,
            tools=tools_schemas,
            messages=messages,
        )

    deadline = asyncio.get_event_loop().time() + settings.agent_timeout_seconds

    while True:
        await _maybe_cancel()
        if iterations >= settings.agent_max_iterations:
            raise AgenticError(f"max_iterations={settings.agent_max_iterations} reached")
        if asyncio.get_event_loop().time() > deadline:
            raise AgenticError(f"timeout exceeded ({settings.agent_timeout_seconds}s)")

        try:
            remaining = max(1.0, deadline - asyncio.get_event_loop().time())
            response = await asyncio.wait_for(_call_anthropic(), timeout=remaining)
        except asyncio.TimeoutError:
            raise AgenticError(f"timeout exceeded ({settings.agent_timeout_seconds}s)")

        iterations += 1
        stop_reason = response.stop_reason or "unknown"

        # Append assistant turn (preserve full content blocks so we can answer tool_use)
        messages.append({"role": "assistant", "content": [b.model_dump() for b in response.content]})

        # Collect text + tool_use blocks
        text_parts: list[str] = []
        tool_use_blocks: list[dict] = []
        for block in response.content:
            d = block.model_dump()
            if d.get("type") == "text":
                text_parts.append(d.get("text", ""))
            elif d.get("type") == "tool_use":
                tool_use_blocks.append(d)
        if text_parts:
            final_text = "\n\n".join(text_parts)

        if stop_reason == "max_tokens":
            raise AgenticError("LLM stop_reason=max_tokens (context/output limit hit)")
        if stop_reason == "end_turn" and not tool_use_blocks:
            break  # natural end
        if not tool_use_blocks:
            # No more tool calls but not end_turn — exit gracefully
            break

        # Execute each tool_use in this turn (sequential for v0.4)
        tool_results: list[dict] = []
        for tu in tool_use_blocks:
            await _maybe_cancel()
            tool_calls += 1
            if tool_calls > settings.agent_max_tool_calls:
                raise AgenticError(f"max_tool_calls={settings.agent_max_tool_calls} reached")

            sig = _call_signature(tu.get("name", ""), tu.get("input", {}))
            recent_calls.append(sig)
            recent_calls[:] = recent_calls[-settings.agent_repeat_pattern_threshold:]
            if (
                len(recent_calls) >= settings.agent_repeat_pattern_threshold
                and len(set(recent_calls)) == 1
            ):
                raise AgenticError(
                    f"repeat pattern detected: same tool+args called {settings.agent_repeat_pattern_threshold} times consecutively"
                )

            step_no += 1
            try:
                result_str = await tool_executor(tu.get("name", ""), tu.get("input", {}))
                step_status = "ok"
            except Exception as e:
                logger.exception("Tool executor raised for %r", tu.get("name"))
                result_str = json.dumps({"ok": False, "error": str(e)[:200]})
                step_status = "error"

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.get("id"),
                "content": result_str,
            })

            if on_step is not None:
                await on_step({
                    "step_no": step_no,
                    "tool_name": tu.get("name", ""),
                    "args_snippet": _truncate(json.dumps(tu.get("input", {}), ensure_ascii=False)),
                    "result_snippet": _truncate(result_str),
                    "ts": _iso_now(),
                    "status": step_status,
                })

        messages.append({"role": "user", "content": tool_results})

    return {
        "final_text": final_text,
        "iterations": iterations,
        "tool_calls": tool_calls,
        "stop_reason": stop_reason,
    }


def _call_signature(tool_name: str, tool_input: dict) -> str:
    encoded = json.dumps(tool_input, sort_keys=True, ensure_ascii=False)
    h = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
    return f"{tool_name}:{h}"


def _truncate(s: str, n: int = 500) -> str:
    if not isinstance(s, str):
        s = str(s)
    return s if len(s) <= n else s[:n] + "…"


def _iso_now() -> str:
    import datetime
    return datetime.datetime.utcnow().isoformat() + "Z"

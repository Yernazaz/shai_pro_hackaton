import os
from typing import Any, Dict, List, Optional

import httpx

from app.utils.openai_config import (
    configure_openai_from_env,
    get_openai_model,
)

try:
    # Legacy OpenAI SDK (0.28.x) for local/OpenAI usage
    import openai  # type: ignore
except Exception:  # pragma: no cover - optional dependency path
    openai = None  # type: ignore


def _as_tools(functions: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
    if not functions:
        return None
    tools: List[Dict[str, Any]] = []
    for f in functions:
        tools.append({
            "type": "function",
            "function": {
                "name": f.get("name"),
                "description": f.get("description"),
                "parameters": f.get("parameters"),
            },
        })
    return tools


def _as_tool_choice(function_call: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not function_call:
        return None
    name = function_call.get("name")
    if not name:
        return None
    return {"type": "function", "function": {"name": name}}


def _use_http_backend() -> bool:
    # Use raw HTTP if a base URL is set and no API key is provided,
    # or explicitly when LLM_BASE_URL is present.
    if os.getenv("LLM_BASE_URL"):
        return True
    # Fallback to OPENAI_API_BASE/OPENAI_BASE_URL when no key is set
    if (os.getenv("OPENAI_API_BASE") or os.getenv("OPENAI_BASE_URL")) and not os.getenv("OPENAI_API_KEY"):
        return True
    return False


def chat_completion(
    messages: List[Dict[str, Any]],
    model: Optional[str] = None,
    temperature: float = 0.0,
    functions: Optional[List[Dict[str, Any]]] = None,
    function_call: Optional[Dict[str, Any]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[Dict[str, Any]] = None,
    max_tokens: Optional[int] = None,
) -> Dict[str, Any]:
    """Create a chat completion using either:
    - Raw HTTP to an OpenAI-compatible server (LLM_BASE_URL, no API key required), or
    - Legacy OpenAI SDK when LLM_BASE_URL is not provided.
    Returns the full JSON response with `choices` list.
    """
    chosen_model = model or get_openai_model()

    if _use_http_backend():
        base_url = (os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_API_BASE") or os.getenv("OPENAI_BASE_URL")).rstrip("/")
        url = f"{base_url}/v1/chat/completions"

        payload: Dict[str, Any] = {
            "model": chosen_model,
            "messages": messages,
            "temperature": temperature,
        }

        # Prefer explicit tools if supplied; otherwise convert legacy functions
        use_tools = tools or _as_tools(functions)
        if use_tools:
            payload["tools"] = use_tools
            if tool_choice or function_call:
                payload["tool_choice"] = tool_choice or _as_tool_choice(function_call)
        elif functions:
            # Some servers still accept legacy `functions`/`function_call`
            payload["functions"] = functions
            if function_call:
                payload["function_call"] = function_call

        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        # No API key / Authorization header by design for this backend
        with httpx.Client(timeout=60) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()

    # SDK path
    if openai is None:
        raise RuntimeError("openai SDK not available and LLM_BASE_URL not set")

    configure_openai_from_env()
    response = openai.ChatCompletion.create(
        model=chosen_model,
        messages=messages,
        temperature=temperature,
        functions=functions,
        function_call=function_call,
        max_tokens=max_tokens,
    )
    # The SDK returns an object with .to_dict_recursive(), but for parity return dict-like
    return response

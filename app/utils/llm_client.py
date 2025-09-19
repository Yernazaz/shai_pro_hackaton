from typing import Any, Dict, List, Optional

from app.utils.gemini_config import (
    get_gemini_api_key,
    get_gemini_model,
)
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

try:  # pragma: no cover - optional dependency path
    import google.generativeai as genai  # type: ignore

    try:
        from google.generativeai import types as genai_types  # type: ignore
    except Exception:  # Older packages expose `generative_models`
        genai_types = None  # type: ignore
except Exception:  # pragma: no cover - optional dependency path
    genai = None  # type: ignore
    genai_types = None  # type: ignore


def _normalise_message_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        fragments: List[str] = []
        for part in content:
            if isinstance(part, dict):
                # Handle structured entries that include nested text fields
                if part.get("type") == "text" and part.get("text"):
                    fragments.append(str(part.get("text")))
                elif "text" in part and part.get("text"):
                    fragments.append(str(part.get("text")))
                else:
                    fragments.append(str(part))
            else:
                fragments.append(str(part))
        return "\n".join([frag for frag in fragments if frag])
    return str(content)


def _convert_messages_for_gemini(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    system_instruction: Optional[str] = None
    contents: List[Dict[str, Any]] = []

    for message in messages:
        role = message.get("role", "user")
        text = _normalise_message_content(message.get("content"))
        if not text:
            continue

        if role == "system":
            system_instruction = (
                f"{system_instruction}\n{text}" if system_instruction else text
            )
            continue

        if role == "assistant":
            role = "model"
        elif role not in {"user", "model"}:
            # Gemini only supports `user`/`model` roles – map everything else to user.
            role = "user"

        contents.append({"role": role, "parts": [{"text": text}]})

    if not contents:
        contents.append({"role": "user", "parts": [{"text": ""}]})

    return {"system_instruction": system_instruction, "contents": contents}


def _build_generation_config(temperature: float, max_tokens: Optional[int]) -> Optional[Any]:
    config: Dict[str, Any] = {}
    # Gemini treats `temperature=None` differently from 0, so only include if provided
    if temperature is not None:
        config["temperature"] = temperature
    if max_tokens is not None:
        config["max_output_tokens"] = max_tokens

    if not config:
        return None

    if genai_types is not None:
        try:
            return genai_types.GenerationConfig(**config)
        except Exception:  # pragma: no cover - defensive fallback
            logger.debug("[LLM] Failed to construct GenerationConfig, using raw dict")
    return config


def _chat_completion_gemini(
    messages: List[Dict[str, Any]],
    model: Optional[str],
    temperature: float,
    max_tokens: Optional[int],
) -> Dict[str, Any]:
    if genai is None:
        raise RuntimeError(
            "google-generativeai SDK not available but GEMINI_API_KEY is configured"
        )

    api_key = get_gemini_api_key()
    if not api_key:
        raise RuntimeError(
            "A Gemini-compatible API key (e.g. GEMINI_API_KEY or GOOGLE_API_KEY) is required"
        )


    genai.configure(api_key=api_key)

    converted = _convert_messages_for_gemini(messages)
    system_instruction = converted.get("system_instruction")
    contents = converted["contents"]

    model_name = model or get_gemini_model()
    if model_name and "gemini" not in model_name.lower():
        logger.debug(
            "[LLM] Overriding non-Gemini model '%s' with Gemini default", model_name
        )
        model_name = get_gemini_model()


    model_kwargs: Dict[str, Any] = {}
    if system_instruction:
        model_kwargs["system_instruction"] = system_instruction

    gemini_model = genai.GenerativeModel(model_name, **model_kwargs)

    generation_config = _build_generation_config(temperature, max_tokens)
    request_kwargs: Dict[str, Any] = {"contents": contents}
    if generation_config is not None:
        request_kwargs["generation_config"] = generation_config

    try:
        response = gemini_model.generate_content(**request_kwargs)
    except Exception as exc:  # pragma: no cover - network/SDK errors
        logger.error("[LLM] Gemini request failed: %s", exc)
        raise RuntimeError(f"Gemini request failed: {exc}") from exc

    text = getattr(response, "text", None)
    if not text:
        try:
            candidates = getattr(response, "candidates", None)
            if candidates:
                first = candidates[0]
                content = getattr(first, "content", None)
                parts = getattr(content, "parts", None)
                if parts:
                    text = "".join(getattr(part, "text", "") or "" for part in parts)
                elif isinstance(first, dict):
                    parts_dict = first.get("content", {}).get("parts") if isinstance(first.get("content"), dict) else first.get("parts")
                    if parts_dict:
                        text = "".join(part.get("text", "") for part in parts_dict)
        except Exception:  # pragma: no cover - best-effort extraction
            text = None

    final_text = (text or "").strip()

    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": final_text,
                }
            }
        ],
        "model": model_name,
    }


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
    """Create a chat completion using the Gemini SDK and return the JSON payload."""
    chosen_model = model or get_gemini_model()

    if functions or tools:
        logger.warning(
            "[LLM] Gemini backend does not currently support tool or function calls; "
            "игнорируем переданные описания."
        )
    if function_call or tool_choice:
        logger.warning(
            "[LLM] Gemini backend не поддерживает явный выбор функции; параметр пропущен."
        )

    return _chat_completion_gemini(
        messages=messages,
        model=chosen_model,
        temperature=temperature,
        max_tokens=max_tokens,
    )

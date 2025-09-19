import os


def _clean(val: str | None) -> str | None:
    if val is None:
        return None
    return val.strip().strip('"').strip("'")


def get_gemini_api_key() -> str | None:
    """Return the configured Gemini-compatible API key if available."""

    for env_name in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GOOGLE_AI_API_KEY",
    ):
        value = _clean(os.getenv(env_name))
        if value:
            return value
    return None


def using_gemini() -> bool:
    """Return True when Gemini access is configured."""

    return bool(get_gemini_api_key())


def get_gemini_model() -> str:
    """Return the default Gemini model identifier."""

    return _clean(os.getenv("GEMINI_MODEL")) or "gemini-1.5-pro"


__all__ = [
    "get_gemini_api_key",
    "get_gemini_model",
    "using_gemini",
]

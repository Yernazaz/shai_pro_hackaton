import os
import openai


def _clean(val: str | None) -> str | None:
    if val is None:
        return None
    # Trim whitespace and accidental surrounding quotes
    return val.strip().strip('"').strip("'")


def configure_openai_from_env() -> None:
    """Configure the legacy openai client from environment variables.

    Supports:
    - `OPENAI_API_KEY` (required for calls)
    - `OPENAI_API_BASE` or `OPENAI_BASE_URL` (optional)
    - `OPENAI_ORG` or `OPENAI_ORGANIZATION` (optional)
    """
    api_key = _clean(os.getenv("OPENAI_API_KEY"))
    if api_key:
        openai.api_key = api_key

    api_base = _clean(os.getenv("OPENAI_API_BASE") or os.getenv("OPENAI_BASE_URL"))
    if api_base:
        openai.api_base = api_base

    org = _clean(os.getenv("OPENAI_ORG") or os.getenv("OPENAI_ORGANIZATION"))
    if org:
        openai.organization = org


def get_openai_model() -> str:
    """Return the model to use for Chat Completions.

    Defaults to `gpt-4o-mini` for good capability/cost and
    compatibility with legacy Chat Completions in openai==0.28.
    Override via `OPENAI_MODEL` env.
    """
    return _clean(os.getenv("OPENAI_MODEL")) or "gpt-4o-mini"

"""
Zwischenzug provider — LangChain model wrappers via LiteLLM.

This is the **single file** that imports LangChain provider integrations.
All chat models are constructed through `langchain_litellm.ChatLiteLLM`, which
lets Zwischenzug route any LiteLLM-supported provider through one consistent
LangChain interface.
"""
from __future__ import annotations

import functools
import os
from typing import Any


# Providers that require no API key — local execution or non-API-key auth.
# These are skipped during credential validation.
_NO_KEY_PROVIDERS: frozenset[str] = frozenset({
    "ollama",
    "ollama_chat",
    "petals",
    # AWS-credential-based (need AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY)
    "bedrock",
    "bedrock_mantle",
    "amazon_nova",
    "aws_polly",
    # Service-account / OAuth-based
    "vertex_ai",
})

# Providers whose credential env vars don't follow LiteLLM's naming convention.
# Values override the convention-derived candidates entirely.
_KEY_OVERRIDES: dict[str, list[str]] = {
    "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],  # two accepted keys
    "fal_ai": ["FAL_KEY"],                            # non-standard name
    "friendliai": ["FRIENDLI_TOKEN"],                 # token, not _API_KEY
    "github_copilot": ["GITHUB_TOKEN"],
    "gradient_ai": ["GRADIENT_ACCESS_TOKEN"],
    "databricks": ["DATABRICKS_TOKEN"],
    "vercel_ai_gateway": ["VERCEL_OIDC_TOKEN"],
    "black_forest_labs": ["BFL_API_KEY"],             # abbreviated name
    "perplexity": ["PERPLEXITYAI_API_KEY"],           # includes "AI" suffix
    "novita": ["NOVITA_AI_API_KEY"],                  # includes "AI" infix
}


@functools.lru_cache(maxsize=1)
def _build_provider_key_map() -> dict[str, list[str]]:
    """
    Derive provider → [env_var, ...] from litellm.provider_list at runtime.

    LiteLLM naming convention (from litellm/utils.py _infer_valid_provider_from_env_vars):
      variant 1 — strip all separators:  TOGETHERAI_API_KEY
      variant 2 — normalize to underscores: TOGETHER_AI_API_KEY

    Providers in _NO_KEY_PROVIDERS are skipped.
    Providers in _KEY_OVERRIDES use those values instead of the convention.
    """
    try:
        import litellm  # type: ignore
    except ImportError:
        return {}

    result: dict[str, list[str]] = {}
    providers = getattr(litellm, "provider_list", [])

    for provider in providers:
        name = str(getattr(provider, "value", provider)).strip().lower()
        if not name or name in _NO_KEY_PROVIDERS:
            continue

        if name in _KEY_OVERRIDES:
            result[name] = _KEY_OVERRIDES[name]
            continue

        # Convention: two variants, deduplicated
        v1 = name.replace("-", "").replace("_", "").upper() + "_API_KEY"
        v2 = name.replace("-", "_").upper() + "_API_KEY"
        keys: list[str] = []
        seen: set[str] = set()
        for k in (v1, v2):
            if k not in seen:
                seen.add(k)
                keys.append(k)
        result[name] = keys

    return result


def resolve_model(provider: str, model: str) -> str:
    """
    Normalize the final LiteLLM model identifier.

    The selected `provider` is authoritative — prefixes the model string so
    LiteLLM routes to the correct backend.
    """
    provider = provider.strip().lower()
    raw_model = model.strip()
    if raw_model.lower().startswith(f"{provider}/"):
        return raw_model
    return f"{provider}/{raw_model}"


def build_llm(provider: str, model: str, **kwargs: Any):
    """
    Factory: return a LiteLLM-backed LangChain chat model.

    Args:
        provider: LiteLLM provider slug (e.g. "groq", "gemini", "openai")
        model:    Model identifier or alias
        **kwargs: temperature, max_tokens, max_retries, api_base, api_key, etc.
    """
    provider = provider.strip().lower()
    resolved_model = resolve_model(provider, model)

    try:
        from langchain_litellm import ChatLiteLLM
    except ImportError as exc:
        raise ImportError(
            "langchain-litellm is not installed.\n"
            "Run: pip install langchain-litellm"
        ) from exc

    _validate_provider_credentials(provider, resolved_model)

    init_kwargs = {
        "model": resolved_model,
        "temperature": kwargs.get("temperature", 0.2),
        "max_tokens": kwargs.get("max_tokens", 8192),
        "max_retries": kwargs.get("max_retries", 2),
        "streaming": kwargs.get("streaming", True),
    }

    for key in (
        "api_base",
        "api_key",
        "organization",
        "custom_llm_provider",
        "include_reasoning",
        "reasoning_effort",
        "reasoning_format",
    ):
        if key in kwargs and kwargs[key] is not None:
            init_kwargs[key] = kwargs[key]

    return ChatLiteLLM(**init_kwargs)


def _validate_provider_credentials(provider: str, resolved_model: str) -> None:
    """
    Raise a friendly error when none of the expected API key env vars are set.

    Uses the dynamically derived key map; unknown providers (not in litellm's
    provider_list) are left to LiteLLM's own validation at call time.
    """
    required_keys = _build_provider_key_map().get(provider)
    if not required_keys:
        return
    if not any(os.getenv(k, "").strip() for k in required_keys):
        hint = " or ".join(required_keys)
        raise ValueError(
            f"No API key found for provider '{provider}'. "
            f"Set {hint} in your .env file or export it before running Zwischenzug."
        )


def available_providers() -> list[str]:
    """Return all LiteLLM provider slugs that Zwischenzug can validate credentials for."""
    return sorted(_build_provider_key_map().keys())


def default_model(provider: str) -> str:
    """No built-in defaults — user must supply a model."""
    return ""


def list_models(provider: str) -> list[str]:
    """No built-in model lists — user supplies the model directly."""
    return []


def provider_env_hint(provider: str) -> str | None:
    """Return the env var hint string for a provider, derived from the key map."""
    keys = _build_provider_key_map().get(provider.strip().lower())
    if not keys:
        return None
    return " or ".join(keys)

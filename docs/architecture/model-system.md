# Model System

## Overview

The model system manages which LLM providers and models are available, how they are selected, and how new providers are added.

---

## Provider Architecture

All provider code lives in `src/provider/__init__.py`. This is the **only file** that imports LangChain's LiteLLM integration and translates Zwischenzug provider/model settings into LiteLLM model IDs.

### Supported Providers

| Provider | Library | Env Variable | Default Model |
|----------|---------|-------------|---------------|
| `groq` | langchain-litellm | `GROQ_API_KEY` | `groq/llama-3.3-70b-versatile` |
| `gemini` | langchain-litellm | `GEMINI_API_KEY` or `GOOGLE_API_KEY` | `gemini/gemini-2.0-flash` |
| `openai` | langchain-litellm | `OPENAI_API_KEY` | `openai/gpt-4.1-nano` |
| `anthropic` | langchain-litellm | `ANTHROPIC_API_KEY` | `anthropic/claude-3-5-sonnet-latest` |

### Model Aliases

Each provider has convenience aliases so users don't need to remember full model IDs:

```python
MODEL_ALIASES = {
    "groq": {
        "versatile": "groq/llama-3.3-70b-versatile",
        "fast": "groq/llama-3.1-8b-instant",
        ...
    },
    "gemini": {
        "flash": "gemini/gemini-2.0-flash",
        "pro": "gemini/gemini-1.5-pro",
        ...
    },
}
```

---

## Model Selection

The model is determined by this priority (highest first):

1. `--model` CLI flag
2. `ZWISCHENZUG_MODEL` environment variable
3. Provider-specific default known to Zwischenzug

The provider is determined by:

1. `--provider` CLI flag
2. `ZWISCHENZUG_PROVIDER` environment variable
3. Provider from `.zwis/config.json`

---

## Adding a New Provider

Most new LiteLLM providers do not require code changes.

1. Set `ZWISCHENZUG_PROVIDER` to the LiteLLM provider slug
2. Set `ZWISCHENZUG_MODEL` to either:
   - a provider-local model name like `gpt-4.1-nano`, which Zwischenzug normalizes to `<provider>/<model>`
   - a namespaced model slug like `openai/gpt-oss-120b`, which Zwischenzug still routes through the selected provider as `<provider>/openai/gpt-oss-120b`
3. Export the provider-specific API key expected by LiteLLM

Only add code when you want Zwischenzug-specific aliases or a provider-specific default model.

---

## Provider Isolation Invariant

This is a non-negotiable architectural principle:

> No file outside `src/provider/__init__.py` may import provider-specific libraries directly. The rest of the codebase talks to LiteLLM-backed LangChain chat models via `build_llm()`.

The rest of the codebase interacts with the LLM exclusively through the `BaseChatModel` interface returned by `build_llm()`.

# Environment Variables

## LLM Provider Configuration

| Variable | Description | Example |
|----------|-------------|---------|
| `ZWISCHENZUG_PROVIDER` | LiteLLM provider slug | `groq`, `gemini`, `openai`, `anthropic` |
| `ZWISCHENZUG_MODEL` | Model alias or provider-scoped model name | `versatile`, `flash`, `openai/gpt-oss-120b` |
| `ZWISCHENZUG_INCLUDE_REASONING` | Enable reasoning output for supported models | `true`, `false` |
| `ZWISCHENZUG_REASONING_EFFORT` | Reasoning effort hint for supported models | `none`, `default`, `low`, `medium`, `high` |
| `ZWISCHENZUG_REASONING_FORMAT` | Provider-specific reasoning format | `parsed` |
| `GROQ_API_KEY` | API key for Groq models | `gsk_...` |
| `GEMINI_API_KEY` | API key for Gemini models | `...` |
| `GOOGLE_API_KEY` | Alternate Gemini credential env var | `...` |
| `OPENAI_API_KEY` | API key for OpenAI models | `sk_...` |
| `ANTHROPIC_API_KEY` | API key for Anthropic models | `...` |
| `OPENROUTER_API_KEY` | API key for OpenRouter models | `...` |

## Browser Agent Configuration

| Variable | Description | Example |
|----------|-------------|---------|
| `BROWSER_AGENT_MODEL` | Override LLM model for the autonomous browser agent | `gemini-2.5-flash`, `gemini-3-flash-preview` |

If `BROWSER_AGENT_MODEL` is not set, the browser agent uses the main `ZWISCHENZUG_MODEL`. The browser agent uses browser-use's native LLM classes (not LiteLLM), so the model name should be the provider's native model ID without the LiteLLM prefix (e.g. `gemini-2.5-flash` not `gemini/gemini-2.5-flash`).

### Provider Resolution

If `--provider` is not specified:
1. Check `ZWISCHENZUG_PROVIDER`
2. Check `.zwis/config.json`
3. Fall back to the built-in default provider (`groq`)

---

## .env File

Zwischenzug reads environment variables from a `.env` file in the project root via `python-dotenv`:

```bash
# .env
ZWISCHENZUG_PROVIDER=groq
ZWISCHENZUG_MODEL=versatile
GROQ_API_KEY=gsk_your_key_here
ZWISCHENZUG_INCLUDE_REASONING=true
ZWISCHENZUG_REASONING_EFFORT=medium

# or
ZWISCHENZUG_PROVIDER=gemini
ZWISCHENZUG_MODEL=flash
GEMINI_API_KEY=your_key_here

# or
ZWISCHENZUG_PROVIDER=openai
ZWISCHENZUG_MODEL=nano
OPENAI_API_KEY=sk_your_key_here
```

Copy from the provided template:
```bash
cp .env.example .env
```

---

## CLI Flag Overrides

CLI flags take precedence over environment variables:

| Flag | Overrides | Description |
|------|-----------|-------------|
| `--provider` | `ZWISCHENZUG_PROVIDER` | LiteLLM provider to use |
| `--model` | `ZWISCHENZUG_MODEL` | Model name, alias, or full LiteLLM model ID |
| `--permission` | — | Permission mode: `auto`, `interactive`, `deny` |
| `--plan` | — | Enable plan mode (read-only) |
| `--temperature` | — | LLM temperature (0.0–1.0) |
| `--max-tokens` | — | Maximum output tokens |
| `--include-reasoning` | `ZWISCHENZUG_INCLUDE_REASONING` | Enable reasoning output for supported models |
| `--no-include-reasoning` | `ZWISCHENZUG_INCLUDE_REASONING` | Disable reasoning output for supported models |
| `--reasoning-effort` | `ZWISCHENZUG_REASONING_EFFORT` | Reasoning effort hint for supported models |
| `--reasoning-format` | `ZWISCHENZUG_REASONING_FORMAT` | Provider-specific reasoning format |
| `--max-turns` | — | Maximum agent turns |
| `--system` | — | Override system prompt |
| `--continue` | — | Resume last session |
| `--resume` | — | Resume a specific session by ID |

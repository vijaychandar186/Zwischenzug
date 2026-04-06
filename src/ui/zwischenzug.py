from __future__ import annotations

import os
from dataclasses import dataclass

from ..provider import build_llm, provider_env_hint, resolve_model


@dataclass(frozen=True)
class ZwischenzugConfig:
    message: str
    model: str
    provider: str
    temperature: float
    max_tokens: int
    max_retries: int
    include_reasoning: bool | None
    reasoning_effort: str | None
    reasoning_format: str | None


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise ValueError(f"Missing required env var: {name}")
    return value.strip()


def _parse_int_env(name: str) -> int:
    raw = _require_env(name)
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Env var {name} must be an integer, got: {raw!r}") from exc


def _parse_float_env(name: str) -> float:
    raw = _require_env(name)
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"Env var {name} must be a float, got: {raw!r}") from exc


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _optional_bool_env(name: str) -> bool | None:
    value = _optional_env(name)
    if value is None:
        return None
    normalized = value.lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Env var {name} must be a boolean, got: {value!r}")


def _require_positive_int(value: int, label: str) -> int:
    if value <= 0:
        raise ValueError(f"{label} must be greater than 0")
    return value


def load_zwischenzug_config(
    message: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    max_retries: int | None = None,
    include_reasoning: bool | None = None,
    reasoning_effort: str | None = None,
    reasoning_format: str | None = None,
) -> ZwischenzugConfig:
    try:
        from dotenv import load_dotenv
    except ImportError as exc:
        raise ValueError("Missing dependency: python-dotenv. Install with `pip install python-dotenv`.") from exc

    load_dotenv(override=False)

    resolved_provider = (provider or _require_env("ZWISCHENZUG_PROVIDER")).strip().lower()

    resolved_max_tokens = _require_positive_int(
        max_tokens if max_tokens is not None else _parse_int_env("ZWISCHENZUG_MAX_TOKENS"),
        "max_tokens",
    )
    resolved_max_retries = _require_positive_int(
        max_retries if max_retries is not None else _parse_int_env("ZWISCHENZUG_MAX_RETRIES"),
        "max_retries",
    )

    return ZwischenzugConfig(
        message=message or _optional_env("ZWISCHENZUG_MESSAGE") or "",
        model=resolve_model(resolved_provider, model or _require_env("ZWISCHENZUG_MODEL")),
        provider=resolved_provider,
        temperature=temperature if temperature is not None else _parse_float_env("ZWISCHENZUG_TEMPERATURE"),
        max_tokens=resolved_max_tokens,
        max_retries=resolved_max_retries,
        include_reasoning=include_reasoning if include_reasoning is not None else _optional_bool_env("ZWISCHENZUG_INCLUDE_REASONING"),
        reasoning_effort=reasoning_effort or _optional_env("ZWISCHENZUG_REASONING_EFFORT"),
        reasoning_format=reasoning_format or _optional_env("ZWISCHENZUG_REASONING_FORMAT"),
    )


def _build_chain(config: ZwischenzugConfig) -> object:
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    prompt = ChatPromptTemplate.from_template(
        "You are Zwischenzug, a coding assistant. Return one concise coding action for: {user_input}"
    )
    model = build_llm(
        config.provider,
        config.model,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        max_retries=config.max_retries,
        streaming=False,
        include_reasoning=config.include_reasoning,
        reasoning_effort=config.reasoning_effort,
        reasoning_format=config.reasoning_format,
    )
    return prompt | model | StrOutputParser()



_ASCII_LOGO = r"""  ______        _          _
 |___  /       (_)        | |
    / /_      ___ ___  ___| |__   ___ _ __  _____   _  __ _
   / /\ \ /\ / / / __|/ __| '_ \ / _ \ '_ \|_  / | | |/ _` |
  / /__\ V  V /| \__ \ (__| | | |  __/ | | |/ /| |_| | (_| |
 /_____|\_/\_/ |_|___/\___|_| |_|\___|_| |_/___|\__,_|\__, |
                                                       __/ |
                                                      |____| """


def run_zwischenzug(config: ZwischenzugConfig) -> int:
    try:
        from rich.console import Console
    except ImportError:
        print("Missing dependency: rich. Install with `pip install rich`.")
        return 1

    try:
        chain = _build_chain(config)
    except ImportError:
        print("Missing provider dependency. Install with `pip install langchain-litellm`.")
        return 1
    except ValueError as exc:
        hint = provider_env_hint(config.provider)
        if hint:
            print(f"{exc}\nCommon env var for provider '{config.provider}': {hint}")
        else:
            print(str(exc))
        return 1

    palette = ["#ff2d95", "#ff6f3c", "#ffd166", "#06d6a0", "#00b4ff", "#7b61ff"]
    con = Console()
    for i, line in enumerate(_ASCII_LOGO.split("\n")):
        con.print(line, style=f"bold {palette[i % len(palette)]}")

    response = str(chain.invoke({"user_input": config.message}))
    con.print(response)
    return 0

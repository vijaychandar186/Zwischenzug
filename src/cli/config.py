"""
Zwischenzug CLI config — AgentConfig resolution and settings.json loading.

Resolution order (highest → lowest priority):
  1. CLI flags passed at runtime
  2. Environment variables (ZWISCHENZUG_*)
  3. .zwis/config.json (with legacy fallback)
  4. Interactive onboarding wizard (first-run)

Settings loading (hooks, permissions):
  - ~/.zwis/settings.json   (user-level)
  - .zwis/settings.json     (project-level, wins on conflict)
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from ..app_paths import app_home, config_file, legacy_config_file, settings_files

CONFIG_DIR = app_home()
CONFIG_FILE = config_file()
LEGACY_CONFIG_FILE = legacy_config_file()


@dataclass
class AgentConfig:
    provider: str
    model: str
    temperature: float = 0.2
    max_tokens: int = 8192
    max_retries: int = 2
    include_reasoning: bool | None = None
    reasoning_effort: str | None = None
    reasoning_format: str | None = None
    permission_mode: str = "interactive"   # auto | interactive | deny
    system_prompt: str = ""
    max_turns: int = 50
    context_window: int = 0  # 0 = use TokenBudget default (200k)
    streaming: bool = True

    def save(self) -> None:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load_file(cls) -> "AgentConfig | None":
        for path in (CONFIG_FILE, LEGACY_CONFIG_FILE):
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
            except Exception:  # noqa: BLE001
                return None
        return None


def resolve_config(
    provider: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    max_retries: int | None = None,
    include_reasoning: bool | None = None,
    reasoning_effort: str | None = None,
    reasoning_format: str | None = None,
    permission_mode: str | None = None,
    system_prompt: str | None = None,
    max_turns: int | None = None,
    context_window: int | None = None,
    skip_wizard: bool = False,
) -> AgentConfig:
    """
    Build an AgentConfig by merging all config sources.
    Runs an interactive wizard on first use if no config exists.
    """
    load_dotenv(override=False)

    # Layer 3: file config (baseline)
    file_cfg = AgentConfig.load_file()

    def _get(flag_val, env_key: str, file_attr: str, default):
        if flag_val is not None:
            return flag_val
        env_val = os.getenv(env_key, "").strip()
        if env_val:
            return env_val
        if file_cfg is not None:
            return getattr(file_cfg, file_attr)
        return default

    resolved_provider = _get(provider, "ZWISCHENZUG_PROVIDER", "provider", None)
    resolved_model = _get(model, "ZWISCHENZUG_MODEL", "model", None)

    # If the provider changed but the model was only inherited from the config
    # file (not explicitly set via CLI or env), reset to the new provider's
    # default so we don't end up with nonsensical combos like
    # "gemini/openai/gpt-oss-120b".
    if resolved_provider and resolved_model:
        _explicit_model = (
            model is not None
            or os.getenv("ZWISCHENZUG_MODEL", "").strip() != ""
        )
        _file_provider = file_cfg.provider if file_cfg else None
        if (
            not _explicit_model
            and _file_provider
            and resolved_provider.lower() != _file_provider.lower()
        ):
            from ..provider import default_model as _dm
            resolved_model = _dm(resolved_provider)

    # Layer 4: wizard if still unresolved — keep asking until configured
    while (not resolved_provider or not resolved_model) and not skip_wizard:
        cfg = _run_wizard()
        cfg.save()
        return cfg

    if not resolved_provider or not resolved_model:
        raise ValueError(
            "No provider/model configured. Set ZWISCHENZUG_PROVIDER and "
            "ZWISCHENZUG_MODEL in your .env or run the setup wizard."
        )

    def _get_num(flag_val, env_key: str, file_attr: str, default, cast):
        if flag_val is not None:
            return flag_val
        env_val = os.getenv(env_key, "").strip()
        if env_val:
            try:
                return cast(env_val)
            except ValueError:
                pass
        if file_cfg is not None:
            return getattr(file_cfg, file_attr)
        return default

    def _get_bool(flag_val, env_key: str, file_attr: str, default):
        if flag_val is not None:
            return flag_val
        env_val = os.getenv(env_key, "").strip().lower()
        if env_val:
            if env_val in {"1", "true", "yes", "on"}:
                return True
            if env_val in {"0", "false", "no", "off"}:
                return False
        if file_cfg is not None:
            return getattr(file_cfg, file_attr)
        return default

    cfg = AgentConfig(
        provider=resolved_provider.lower(),
        model=resolved_model,
        temperature=_get_num(temperature, "ZWISCHENZUG_TEMPERATURE", "temperature", 0.2, float),
        max_tokens=_get_num(max_tokens, "ZWISCHENZUG_MAX_TOKENS", "max_tokens", 8192, int),
        max_retries=_get_num(max_retries, "ZWISCHENZUG_MAX_RETRIES", "max_retries", 2, int),
        include_reasoning=_get_bool(include_reasoning, "ZWISCHENZUG_INCLUDE_REASONING", "include_reasoning", None),
        reasoning_effort=_get(reasoning_effort, "ZWISCHENZUG_REASONING_EFFORT", "reasoning_effort", None),
        reasoning_format=_get(reasoning_format, "ZWISCHENZUG_REASONING_FORMAT", "reasoning_format", None),
        permission_mode=_get(permission_mode, "ZWISCHENZUG_PERMISSION", "permission_mode", "interactive"),
        system_prompt=_get(system_prompt, "ZWISCHENZUG_SYSTEM", "system_prompt", ""),
        max_turns=_get_num(max_turns, "ZWISCHENZUG_MAX_TURNS", "max_turns", 50, int),
        context_window=_get_num(context_window, "ZWISCHENZUG_CONTEXT_WINDOW", "context_window", 0, int),
        streaming=_get_bool(None, "ZWISCHENZUG_STREAMING", "streaming", True),
    )
    if not skip_wizard:
        _, selected_provider, selected_model = _ensure_env_file(cfg.provider, cfg.model)
        if selected_provider and selected_model:
            cfg.provider = selected_provider
            cfg.model = selected_model
    return cfg


def env_file_path(cwd: str | None = None) -> Path:
    """Return the expected .env file path for the given cwd."""
    return _env_file(cwd)


def has_env_file(cwd: str | None = None) -> bool:
    """Whether a .env file exists for the given cwd, or env vars are already set."""
    if env_file_path(cwd).exists():
        return True
    return bool(os.getenv("ZWISCHENZUG_PROVIDER") and os.getenv("ZWISCHENZUG_MODEL"))


def run_init_setup(cwd: str | None = None) -> AgentConfig:
    """
    Explicit interactive setup entrypoint used by `zwis --init`.
    Creates .env when missing (copying from .env.example) and stores
    provider/model in config.json. Re-runs the wizard if provider/model
    are missing even when .env already exists.
    """
    print("\n╔══════════════════════════════════════╗")
    print("║   Zwischenzug — Init Setup            ║")
    print("╚══════════════════════════════════════╝\n")

    env_path = _env_file(cwd)
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)
        provider = os.getenv("ZWISCHENZUG_PROVIDER", "").strip().lower()
        model = os.getenv("ZWISCHENZUG_MODEL", "").strip()
        if provider and model:
            cfg = AgentConfig(provider=provider, model=model)
            cfg.save()
            return cfg

        # .env exists but is incomplete — prompt and patch it in place
        print(f".env found at {env_path} but provider/model are missing. Let's fill them in.\n")
        chosen_provider = _prompt_provider_choice()
        chosen_model = _prompt_model_choice(chosen_provider)

        text = env_path.read_text(encoding="utf-8")
        text = _set_env_value(text, "ZWISCHENZUG_PROVIDER", chosen_provider)
        text = _set_env_value(text, "ZWISCHENZUG_MODEL", chosen_model)
        env_path.write_text(text, encoding="utf-8")
        print(f"Updated {env_path}")

        cfg = AgentConfig(provider=chosen_provider, model=chosen_model)
        cfg.save()
        return cfg

    _, provider, model = _ensure_env_file("", "", cwd=cwd)
    if not provider or not model:
        raise ValueError("Initialization cancelled.")

    cfg = AgentConfig(provider=provider, model=model)
    cfg.save()
    return cfg


def load_settings(cwd: str | None = None) -> dict[str, Any]:
    """
    Load and merge settings.json from user (~/.zwis/settings.json) and project
    (.zwis/settings.json) levels.

    Project settings win over user settings for conflicting top-level keys.
    Sub-keys within 'hooks' and 'permissions' are merged with project overrides.

    Returns the merged settings dict (empty dict if no files exist).
    """
    merged: dict[str, Any] = {}

    for path in settings_files(cwd):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.getLogger("zwischenzug.config").warning(
                "Failed to load %s: %s", path, exc
            )
            continue

        if not isinstance(data, dict):
            continue

        # Deep-merge hooks: project overrides user per event
        if "hooks" in data:
            if "hooks" not in merged:
                merged["hooks"] = {}
            merged["hooks"].update(data["hooks"])

        # Deep-merge permissions: project overrides user
        if "permissions" in data:
            if "permissions" not in merged:
                merged["permissions"] = {}
            merged["permissions"].update(data["permissions"])

        # All other keys: project wins (later file wins)
        for key, value in data.items():
            if key not in ("hooks", "permissions"):
                merged[key] = value

    return merged


def _discover_litellm_providers() -> list[str]:
    providers: set[str] = set()
    try:
        import litellm  # type: ignore
    except ImportError:
        return []

    models_by_provider = getattr(litellm, "models_by_provider", None)
    if isinstance(models_by_provider, dict):
        for provider in models_by_provider:
            name = str(provider).strip().lower()
            if name:
                providers.add(name)

    if not providers:
        provider_list = getattr(litellm, "provider_list", None)
        if isinstance(provider_list, (list, tuple, set)):
            for provider in provider_list:
                raw = getattr(provider, "value", provider)
                name = str(raw).strip().lower()
                if name:
                    providers.add(name)

    if not providers:
        return []

    return sorted(providers)


def _discover_litellm_models(provider: str) -> list[str]:
    try:
        import litellm  # type: ignore
    except ImportError:
        return []

    models_by_provider = getattr(litellm, "models_by_provider", None)
    if not isinstance(models_by_provider, dict):
        return []

    raw_models = models_by_provider.get(provider.strip().lower())
    if raw_models is None:
        return []

    if isinstance(raw_models, dict):
        values = list(raw_models.keys())
    elif isinstance(raw_models, (list, tuple, set)):
        values = list(raw_models)
    else:
        values = [raw_models]

    models = sorted({str(model).strip() for model in values if str(model).strip()})
    return models


def _prompt_provider_choice() -> str:
    providers = _discover_litellm_providers()
    print("Choose your LLM provider:")
    for i, provider in enumerate(providers, 1):
        print(f"  {i}) {provider}")

    while True:
        try:
            choice = input("\nProvider (number): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSetup cancelled.")
            sys.exit(1)

        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(providers):
                return providers[idx]

        normalized = choice.lower()
        if normalized in providers:
            return normalized

        print("  Invalid choice. Enter a number from the list.")


def _prompt_model_choice(provider: str) -> str:
    models = _discover_litellm_models(provider)

    if not models:
        print(f"\nNo LiteLLM model catalog found for provider '{provider}'.")
        while True:
            try:
                model = input("Enter model ID: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                model = ""
            if model:
                return model
            print("  Model cannot be empty.")

    print(f"\nChoose model for provider '{provider}':")
    for i, model in enumerate(models, 1):
        print(f"  {i}) {model}")

    while True:
        try:
            choice = input("\nModel (number): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSetup cancelled.")
            sys.exit(1)

        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(models):
                return models[idx]

        if choice in models:
            return choice

        print("  Invalid choice. Enter a number from the list.")


def _run_wizard() -> AgentConfig:
    """Interactive first-run onboarding wizard."""
    print("\n╔══════════════════════════════════════╗")
    print("║   Zwischenzug — First-Run Setup       ║")
    print("╚══════════════════════════════════════╝\n")

    provider = _prompt_provider_choice()
    model = _prompt_model_choice(provider)

    _ensure_env_file(provider, model)

    print(f"\nConfiguration saved to {CONFIG_FILE}")
    print("Set your API key in .env or as an environment variable:\n")
    from ..provider import provider_env_hint as _peh
    hint = _peh(provider)
    if hint:
        print(f"  export {hint.split(' or ')[0]}=your_key_here")
    else:
        print("  Export the provider-specific API key expected by LiteLLM.")
    print()

    return AgentConfig(provider=provider, model=model)


def _is_interactive_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _env_file(cwd: str | None = None) -> Path:
    base = Path(cwd) if cwd is not None else Path.cwd()
    return base / ".env"


def _env_example_file(cwd: str | None = None) -> Path:
    base = Path(cwd) if cwd is not None else Path.cwd()
    return base / ".env.example"


def _load_env_template(cwd: str | None = None) -> str:
    """
    Load the .env template text, trying in order:
      1. .env.example in the working directory (repo / project)
      2. env.example shipped as package data (pip-install users)
      3. Minimal hardcoded fallback
    """
    local = _env_example_file(cwd)
    if local.exists():
        return local.read_text(encoding="utf-8")

    try:
        from importlib.resources import files
        return files("src.data").joinpath("env.example").read_text(encoding="utf-8")
    except Exception:
        pass

    return (
        "ZWISCHENZUG_PROVIDER=\n"
        "ZWISCHENZUG_MODEL=\n"
        "ZWISCHENZUG_TEMPERATURE=0.2\n"
        "ZWISCHENZUG_MAX_TOKENS=4096\n"
        "ZWISCHENZUG_MAX_RETRIES=2\n"
        "ZWISCHENZUG_PERMISSION=auto\n"
    )


def ensure_credentials(cwd: str | None = None, *, prompt: bool = True) -> bool:
    """
    Check whether the configured provider has an API key set.

    If *prompt* is True and the key is missing, ask the user interactively and
    save the answer to the .env file.  If *prompt* is False (used right after
    init when the user already saw the key question once), only check and return.

    Returns True when credentials are present (or not needed), False otherwise.
    """
    env_path = _env_file(cwd)
    load_dotenv(dotenv_path=env_path, override=False)

    provider = os.getenv("ZWISCHENZUG_PROVIDER", "").strip().lower()
    if not provider:
        return True  # no provider yet — wizard handles it

    from ..provider import _build_provider_key_map
    required_keys = _build_provider_key_map().get(provider)
    if not required_keys:
        return True  # local provider or no key needed

    if any(os.getenv(k, "").strip() for k in required_keys):
        return True  # already set

    if not prompt or not _is_interactive_terminal():
        return False  # missing but we won't prompt

    key_name = required_keys[0]
    print(f"\nNo API key set for provider '{provider}'.")
    try:
        api_key = input(f"Enter {key_name}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return False

    if not api_key:
        return False

    os.environ[key_name] = api_key
    if env_path.exists():
        text = env_path.read_text(encoding="utf-8")
        text = _set_env_value(text, key_name, api_key)
        env_path.write_text(text, encoding="utf-8")
    return True


def _ensure_env_file(provider: str, model: str, cwd: str | None = None) -> tuple[Path | None, str | None, str | None]:
    env_path = _env_file(cwd)
    if env_path.exists() or not _is_interactive_terminal():
        return (env_path if env_path.exists() else None, None, None)

    print(f"\nNo .env file found at {env_path}.")
    try:
        create_now = input("Create one now from .env.example? [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return None, None, None

    if create_now not in ("", "y", "yes"):
        return None, None, None

    text = _load_env_template(cwd)

    chosen_provider = _prompt_provider_choice()
    chosen_model = _prompt_model_choice(chosen_provider)

    text = _set_env_value(text, "ZWISCHENZUG_PROVIDER", chosen_provider)
    text = _set_env_value(text, "ZWISCHENZUG_MODEL", chosen_model)

    from ..provider import _build_provider_key_map
    required_keys = _build_provider_key_map().get(chosen_provider, [])
    api_key_name = required_keys[0] if required_keys else None

    if api_key_name:
        try:
            api_key = input(f"{chosen_provider} API key ({api_key_name}) — press Enter to add it to .env manually: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            api_key = ""
        text = _set_env_value(text, api_key_name, api_key)

    env_path.write_text(text, encoding="utf-8")
    print(f"Wrote {env_path}")
    return env_path, chosen_provider, chosen_model


def _set_env_value(text: str, key: str, value: str) -> str:
    lines = text.splitlines()
    rendered = f"{key}={value}"
    replaced = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        uncommented = stripped[1:].strip() if stripped.startswith("#") else stripped
        if uncommented.startswith(f"{key}="):
            lines[i] = rendered
            replaced = True
            break

    if not replaced:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(rendered)

    return "\n".join(lines) + ("\n" if text.endswith("\n") or not text else "")

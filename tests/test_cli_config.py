"""
Tests for src/cli/config — layered configuration resolution.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.cli.config import AgentConfig, _ensure_env_file, _set_env_value, resolve_config
from src.main import _build_clean_parser


class TestAgentConfig:
    def test_default_values(self):
        cfg = AgentConfig(provider="groq", model="llama-3")
        assert cfg.temperature == 0.2
        assert cfg.max_tokens == 8192
        assert cfg.max_retries == 2
        assert cfg.permission_mode == "interactive"
        assert cfg.system_prompt == ""
        assert cfg.max_turns == 50

    def test_save_and_load(self, tmp_path):
        with patch("src.cli.config.CONFIG_DIR", tmp_path), \
             patch("src.cli.config.CONFIG_FILE", tmp_path / "config.json"):
            cfg = AgentConfig(provider="groq", model="test-model", temperature=0.5)
            cfg.save()
            loaded = AgentConfig.load_file()
            assert loaded is not None
            assert loaded.provider == "groq"
            assert loaded.model == "test-model"
            assert loaded.temperature == 0.5

    def test_load_file_returns_none_when_missing(self, tmp_path):
        with patch("src.cli.config.CONFIG_FILE", tmp_path / "no-config.json"):
            assert AgentConfig.load_file() is None

    def test_save_creates_config_directory(self, tmp_path):
        cfg_dir = tmp_path / "nested" / "config"
        cfg_file = cfg_dir / "config.json"
        with patch("src.cli.config.CONFIG_DIR", cfg_dir), \
             patch("src.cli.config.CONFIG_FILE", cfg_file):
            AgentConfig(provider="groq", model="m").save()
            assert cfg_dir.is_dir()
            assert cfg_file.exists()

    def test_save_writes_valid_json(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        with patch("src.cli.config.CONFIG_DIR", tmp_path), \
             patch("src.cli.config.CONFIG_FILE", cfg_file):
            AgentConfig(provider="gemini", model="gemini-pro").save()
            data = json.loads(cfg_file.read_text())
            assert data["provider"] == "gemini"
            assert data["model"] == "gemini-pro"

    def test_load_file_uses_legacy_config_fallback(self, tmp_path):
        legacy = tmp_path / "legacy-config.json"
        legacy.write_text(json.dumps({"provider": "gemini", "model": "legacy-model"}))
        with patch("src.cli.config.CONFIG_FILE", tmp_path / "missing.json"), \
             patch("src.cli.config.LEGACY_CONFIG_FILE", legacy):
            loaded = AgentConfig.load_file()
        assert loaded is not None
        assert loaded.model == "legacy-model"


class TestResolveConfig:
    def test_cli_flags_take_highest_priority(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ZWISCHENZUG_PROVIDER", "gemini")
        monkeypatch.setenv("ZWISCHENZUG_MODEL", "env-model")
        with patch("src.cli.config.CONFIG_FILE", tmp_path / "missing.json"), \
             patch("src.cli.config.load_dotenv"):
            cfg = resolve_config(provider="groq", model="flag-model", skip_wizard=True)
        assert cfg.provider == "groq"
        assert cfg.model == "flag-model"

    def test_env_vars_used_when_no_flags(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ZWISCHENZUG_PROVIDER", "groq")
        monkeypatch.setenv("ZWISCHENZUG_MODEL", "env-model")
        with patch("src.cli.config.CONFIG_FILE", tmp_path / "missing.json"), \
             patch("src.cli.config.load_dotenv"):
            cfg = resolve_config(skip_wizard=True)
        assert cfg.provider == "groq"
        assert cfg.model == "env-model"

    def test_file_config_used_as_fallback(self, monkeypatch, tmp_path):
        monkeypatch.delenv("ZWISCHENZUG_PROVIDER", raising=False)
        monkeypatch.delenv("ZWISCHENZUG_MODEL", raising=False)
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"provider": "gemini", "model": "file-model"}))
        # Prevent load_dotenv from re-introducing env vars from the workspace .env
        with patch("src.cli.config.CONFIG_FILE", cfg_file), \
             patch("src.cli.config.load_dotenv"):
            cfg = resolve_config(skip_wizard=True)
        assert cfg.provider == "gemini"
        assert cfg.model == "file-model"

    def test_numeric_env_vars_parsed(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ZWISCHENZUG_PROVIDER", "groq")
        monkeypatch.setenv("ZWISCHENZUG_MODEL", "m")
        monkeypatch.setenv("ZWISCHENZUG_TEMPERATURE", "0.7")
        monkeypatch.setenv("ZWISCHENZUG_MAX_TOKENS", "2048")
        monkeypatch.setenv("ZWISCHENZUG_MAX_RETRIES", "5")
        with patch("src.cli.config.CONFIG_FILE", tmp_path / "missing.json"):
            cfg = resolve_config(skip_wizard=True)
        assert cfg.temperature == pytest.approx(0.7)
        assert cfg.max_tokens == 2048
        assert cfg.max_retries == 5

    def test_reasoning_env_vars_parsed(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ZWISCHENZUG_PROVIDER", "groq")
        monkeypatch.setenv("ZWISCHENZUG_MODEL", "m")
        monkeypatch.setenv("ZWISCHENZUG_INCLUDE_REASONING", "true")
        monkeypatch.setenv("ZWISCHENZUG_REASONING_EFFORT", "high")
        monkeypatch.setenv("ZWISCHENZUG_REASONING_FORMAT", "parsed")
        with patch("src.cli.config.CONFIG_FILE", tmp_path / "missing.json"):
            cfg = resolve_config(skip_wizard=True)
        assert cfg.include_reasoning is True
        assert cfg.reasoning_effort == "high"
        assert cfg.reasoning_format == "parsed"

    def test_permission_mode_resolved_from_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ZWISCHENZUG_PROVIDER", "groq")
        monkeypatch.setenv("ZWISCHENZUG_MODEL", "m")
        monkeypatch.setenv("ZWISCHENZUG_PERMISSION", "deny")
        with patch("src.cli.config.CONFIG_FILE", tmp_path / "missing.json"):
            cfg = resolve_config(skip_wizard=True)
        assert cfg.permission_mode == "deny"

    def test_flag_overrides_env_numeric(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ZWISCHENZUG_PROVIDER", "groq")
        monkeypatch.setenv("ZWISCHENZUG_MODEL", "m")
        monkeypatch.setenv("ZWISCHENZUG_MAX_TOKENS", "1024")
        with patch("src.cli.config.CONFIG_FILE", tmp_path / "missing.json"):
            cfg = resolve_config(max_tokens=8192, skip_wizard=True)
        assert cfg.max_tokens == 8192


class TestEnvScaffolding:
    def test_set_env_value_replaces_existing_line(self):
        text = "ZWISCHENZUG_PROVIDER=groq\nZWISCHENZUG_MODEL=fast\n"
        updated = _set_env_value(text, "ZWISCHENZUG_MODEL", "large")
        assert "ZWISCHENZUG_MODEL=large" in updated
        assert "ZWISCHENZUG_MODEL=fast" not in updated

    def test_set_env_value_uncomments_matching_key(self):
        text = "# GOOGLE_API_KEY=\n"
        updated = _set_env_value(text, "GOOGLE_API_KEY", "secret")
        assert "GOOGLE_API_KEY=secret" in updated
        assert "# GOOGLE_API_KEY=" not in updated

    def test_set_env_value_appends_missing_key(self):
        text = "ZWISCHENZUG_PROVIDER=groq\n"
        updated = _set_env_value(text, "GROQ_API_KEY", "abc123")
        assert updated.endswith("GROQ_API_KEY=abc123\n")


class TestCLIFlags:
    def test_reasoning_flags_are_exposed_on_chat_command(self):
        parser = _build_clean_parser()
        args = parser.parse_args(
            [
                "chat",
                "--include-reasoning",
                "--reasoning-effort",
                "high",
                "--reasoning-format",
                "parsed",
            ]
        )
        assert args.include_reasoning is True
        assert args.reasoning_effort == "high"
        assert args.reasoning_format == "parsed"

class TestEnvBootstrapFlow:
    def test_ensure_env_file_prompts_provider_model_api_key(self, monkeypatch, tmp_path):
        env_example = tmp_path / ".env.example"
        env_example.write_text(
            "ZWISCHENZUG_PROVIDER=gemini\n"
            "ZWISCHENZUG_MODEL=flash\n"
            "# OPENAI_API_KEY=\n"
        )

        monkeypatch.setattr("src.cli.config._is_interactive_terminal", lambda: True)
        monkeypatch.setattr("src.cli.config._discover_litellm_providers", lambda: ["groq", "openai"])
        monkeypatch.setattr("src.cli.config._discover_litellm_models", lambda provider: ["openai/gpt-5.4-nano", "openai/gpt-5.4-mini"])

        prompts: list[str] = []
        answers = iter(["y", "2", "1", "sk-test"])

        def _fake_input(prompt: str = "") -> str:
            prompts.append(prompt)
            return next(answers)

        monkeypatch.setattr("builtins.input", _fake_input)

        env_path, selected_provider, selected_model = _ensure_env_file(
            "groq",
            "openai/gpt-oss-120b",
            cwd=str(tmp_path),
        )

        assert env_path == tmp_path / ".env"
        assert selected_provider == "openai"
        assert selected_model == "openai/gpt-5.4-nano"

        rendered = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "ZWISCHENZUG_PROVIDER=openai" in rendered
        assert "ZWISCHENZUG_MODEL=openai/gpt-5.4-nano" in rendered
        assert "OPENAI_API_KEY=sk-test" in rendered

        assert prompts[0].startswith("Create one now from .env.example?")
        assert prompts[1].startswith("\nProvider (number):")
        assert prompts[2].startswith("\nModel (number):")
        assert prompts[3].startswith("openai API key")

    def test_resolve_config_uses_provider_model_selected_during_env_bootstrap(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ZWISCHENZUG_PROVIDER", "groq")
        monkeypatch.setenv("ZWISCHENZUG_MODEL", "versatile")

        with patch("src.cli.config.CONFIG_FILE", tmp_path / "missing.json"), \
             patch("src.cli.config._ensure_env_file", return_value=(None, "openai", "openai/gpt-5.4-nano")), \
             patch("src.cli.config.load_dotenv"):
            cfg = resolve_config(skip_wizard=False)

        assert cfg.provider == "openai"
        assert cfg.model == "openai/gpt-5.4-nano"

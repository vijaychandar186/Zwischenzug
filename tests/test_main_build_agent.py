from __future__ import annotations

import argparse
from unittest.mock import patch

import pytest

from src.cli.config import AgentConfig
from src.main import _build_agent, main


def test_build_agent_missing_api_key_prints_env_guidance(capsys):
    args = argparse.Namespace(plan=False)

    with patch("src.cli.config.resolve_config", return_value=AgentConfig(provider="groq", model="versatile")), \
         patch("src.provider.resolve_model", return_value="groq/openai/gpt-oss-120b"), \
         patch("src.provider.build_llm", side_effect=ValueError("GROQ_API_KEY is not set")):
        with pytest.raises(SystemExit) as exc_info:
            _build_agent(args)

    assert exc_info.value.code == 1
    stderr = capsys.readouterr().err
    assert "Missing provider credentials" in stderr
    assert "Set your env variables" in stderr
    assert "export ZWISCHENZUG_PROVIDER=groq" in stderr
    assert "export ZWISCHENZUG_MODEL=groq/openai/gpt-oss-120b" in stderr
    assert "export GROQ_API_KEY=your_key_here" in stderr


def test_build_agent_resolve_config_skips_wizard():
    args = argparse.Namespace(
        plan=False,
        provider=None,
        model=None,
        temperature=None,
        max_tokens=None,
        max_retries=None,
        include_reasoning=None,
        reasoning_effort=None,
        reasoning_format=None,
        permission_mode=None,
        system=None,
        max_turns=None,
        context_window=None,
    )
    cfg = AgentConfig(provider="openai", model="gpt-5.4-nano")
    with patch("src.cli.config.resolve_config", return_value=cfg) as mock_resolve, \
         patch("src.provider.resolve_model", return_value="openai/gpt-5.4-nano"), \
         patch("src.provider.build_llm", return_value=object()):
        _build_agent(args)

    assert mock_resolve.call_args.kwargs.get("skip_wizard") is True


def test_main_no_env_prints_init_hint(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rc = main([])
    assert rc == 1
    assert "Run `zwis --init`" in capsys.readouterr().err


def test_main_init_runs_setup(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    with patch("src.cli.config.run_init_setup", return_value=AgentConfig(provider="openai", model="gpt-5.4-nano")):
        rc = main(["--init"])
    assert rc == 0
    assert "Initialization complete." in capsys.readouterr().out

from __future__ import annotations

import sys
import types

from src.ui.zwischenzug import load_zwischenzug_config, run_zwischenzug


class _FakeChatLiteLLM:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def complete(self, prompt: str, values: dict[str, str]) -> str:
        user_input = values.get("user_input", "")
        return f"{self.kwargs['model']} :: {user_input}"


class _FakePromptTemplate:
    def __init__(self, template: str):
        self.template = template

    @classmethod
    def from_template(cls, template: str) -> "_FakePromptTemplate":
        return cls(template)

    def __or__(self, model: _FakeChatLiteLLM) -> "_FakePromptModelChain":
        return _FakePromptModelChain(self.template, model)


class _FakePromptModelChain:
    def __init__(self, template: str, model: _FakeChatLiteLLM):
        self.template = template
        self.model = model

    def __or__(self, parser: object) -> "_FakeChain":
        return _FakeChain(self.template, self.model, parser)


class _FakeChain:
    def __init__(self, template: str, model: _FakeChatLiteLLM, parser: object):
        self.template = template
        self.model = model
        self.parser = parser

    def invoke(self, values: dict[str, str]) -> str:
        rendered = self.template.format(**values)
        return self.model.complete(rendered, values)


class _FakeStrOutputParser:
    pass


class _FakeConsole:
    instances: list["_FakeConsole"] = []

    def __init__(self):
        self.lines: list[str] = []
        _FakeConsole.instances.append(self)

    def print(self, value: object, style: str | None = None) -> None:
        self.lines.append(str(value))


def _install_fake_langchain_litellm(monkeypatch) -> None:
    module = types.ModuleType("langchain_litellm")
    module.ChatLiteLLM = _FakeChatLiteLLM
    monkeypatch.setitem(sys.modules, "langchain_litellm", module)


def _install_fake_langchain_core(monkeypatch) -> None:
    prompts_module = types.ModuleType("langchain_core.prompts")
    prompts_module.ChatPromptTemplate = _FakePromptTemplate
    output_parsers_module = types.ModuleType("langchain_core.output_parsers")
    output_parsers_module.StrOutputParser = _FakeStrOutputParser
    monkeypatch.setitem(sys.modules, "langchain_core.prompts", prompts_module)
    monkeypatch.setitem(sys.modules, "langchain_core.output_parsers", output_parsers_module)


def _install_fake_rich(monkeypatch) -> None:
    rich_module = types.ModuleType("rich")
    console_module = types.ModuleType("rich.console")
    console_module.Console = _FakeConsole
    monkeypatch.setitem(sys.modules, "rich", rich_module)
    monkeypatch.setitem(sys.modules, "rich.console", console_module)


def test_run_zwischenzug_smoke_with_litellm(monkeypatch):
    _FakeConsole.instances.clear()
    _install_fake_langchain_litellm(monkeypatch)
    _install_fake_langchain_core(monkeypatch)
    _install_fake_rich(monkeypatch)

    monkeypatch.setenv("ZWISCHENZUG_PROVIDER", "openai")
    monkeypatch.setenv("ZWISCHENZUG_MODEL", "nano")
    monkeypatch.setenv("ZWISCHENZUG_TEMPERATURE", "0.1")
    monkeypatch.setenv("ZWISCHENZUG_MAX_TOKENS", "256")
    monkeypatch.setenv("ZWISCHENZUG_MAX_RETRIES", "3")
    monkeypatch.setenv("ZWISCHENZUG_INCLUDE_REASONING", "true")
    monkeypatch.setenv("ZWISCHENZUG_REASONING_EFFORT", "high")
    monkeypatch.setenv("ZWISCHENZUG_REASONING_FORMAT", "parsed")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    config = load_zwischenzug_config(message="say hello")
    exit_code = run_zwischenzug(config)

    assert exit_code == 0
    assert config.provider == "openai"
    assert config.model == "openai/gpt-5.4-nano"
    assert config.include_reasoning is True
    assert config.reasoning_effort == "high"
    assert config.reasoning_format == "parsed"
    assert _FakeConsole.instances
    last_console = _FakeConsole.instances[-1]
    assert any("openai/gpt-5.4-nano :: say hello" in line for line in last_console.lines)

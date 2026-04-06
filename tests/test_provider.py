from __future__ import annotations

import sys
import types

import pytest

from src.provider import build_llm, default_model, provider_env_hint, resolve_model


class _FakeChatLiteLLM:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.model_name = kwargs.get("model")


def _install_fake_langchain_litellm(monkeypatch):
    module = types.ModuleType("langchain_litellm")
    module.ChatLiteLLM = _FakeChatLiteLLM
    monkeypatch.setitem(sys.modules, "langchain_litellm", module)


class TestResolveModel:
    def test_resolve_model_prefixes_groq_alias(self):
        assert resolve_model("groq", "versatile") == "groq/llama-3.3-70b-versatile"

    def test_resolve_model_prefixes_gemini_alias(self):
        assert resolve_model("gemini", "flash") == "gemini/gemini-3-flash-preview"

    def test_resolve_model_keeps_same_provider_prefix(self):
        assert resolve_model("openai", "openai/gpt-5.4-nano") == "openai/gpt-5.4-nano"

    def test_resolve_model_prefixes_namespaced_model_with_selected_provider(self):
        assert resolve_model("groq", "openai/gpt-oss-120b") == "groq/openai/gpt-oss-120b"


class TestBuildLLM:
    def test_build_llm_uses_langchain_litellm(self, monkeypatch):
        _install_fake_langchain_litellm(monkeypatch)
        monkeypatch.setenv("GROQ_API_KEY", "test-key")

        llm = build_llm(
            "groq",
            "versatile",
            temperature=0.4,
            max_tokens=123,
            max_retries=7,
            include_reasoning=True,
            reasoning_effort="high",
            reasoning_format="parsed",
        )

        assert isinstance(llm, _FakeChatLiteLLM)
        assert llm.kwargs["model"] == "groq/llama-3.3-70b-versatile"
        assert llm.kwargs["temperature"] == 0.4
        assert llm.kwargs["max_tokens"] == 123
        assert llm.kwargs["max_retries"] == 7
        assert llm.kwargs["include_reasoning"] is True
        assert llm.kwargs["reasoning_effort"] == "high"
        assert llm.kwargs["reasoning_format"] == "parsed"

    def test_build_llm_accepts_google_api_key_for_gemini(self, monkeypatch):
        _install_fake_langchain_litellm(monkeypatch)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

        llm = build_llm("gemini", "flash")
        assert llm.kwargs["model"] == "gemini/gemini-3-flash-preview"

    def test_build_llm_requires_known_env_for_openai(self, monkeypatch):
        _install_fake_langchain_litellm(monkeypatch)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            build_llm("openai", "nano")


class TestProviderMetadata:
    def test_default_model_for_groq(self):
        assert default_model("groq") == "openai/gpt-oss-120b"

    def test_provider_env_hint(self):
        assert provider_env_hint("gemini") == "GEMINI_API_KEY or GOOGLE_API_KEY"

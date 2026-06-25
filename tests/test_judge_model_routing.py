"""LLM resolver routing tests:
  - role=lcm/concept_classifier always lands on qwen3:8b.
  - PROMPTEVO_FAST_DEBUG must NOT silently downgrade an explicit
    JUDGE_MODEL=qwen3:8b to llama3.2:1b.
"""
from __future__ import annotations

import importlib

import pytest


def _reload_resolver(monkeypatch, env: dict[str, str]):
    """Reload config + llm_resolver under a fresh env so settings re-init."""
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import config as cfg
    importlib.reload(cfg)
    from core import llm_resolver
    importlib.reload(llm_resolver)
    return cfg, llm_resolver


def _resolve_provider_and_model(monkeypatch, role: str, env: dict[str, str]):
    """Helper that captures the provider/model the resolver would build.

    We patch _build_chat_model so we don't actually need Ollama running.
    The first positional arg of _build_chat_model is the provider; the
    second is the model.
    """
    cfg, llm_resolver = _reload_resolver(monkeypatch, env)
    captured: dict[str, str] = {}

    def fake_build(provider, model, *args, **kwargs):
        captured["provider"] = provider
        captured["model"] = model
        return object()  # non-None sentinel so resolver returns it

    monkeypatch.setattr(cfg, "_build_chat_model", fake_build)
    llm_resolver.resolve_llm(None, f"{role}_llm", f"get_{role}_llm")
    return captured


def test_lcm_resolver_uses_qwen3(monkeypatch):
    captured = _resolve_provider_and_model(
        monkeypatch,
        role="lcm",
        env={
            "LCM_PROVIDER": "ollama",
            "LCM_MODEL": "qwen3:8b",
            "LCM_MODE": "hybrid",
        },
    )
    assert captured["provider"] == "ollama"
    assert captured["model"] == "qwen3:8b"


def test_fast_debug_does_not_override_explicit_judge_model_unless_env_set(monkeypatch):
    captured = _resolve_provider_and_model(
        monkeypatch,
        role="judge",
        env={
            "JUDGE_MODEL": "qwen3:8b",
            "JUDGE_PROVIDER": "ollama",
            "PROMPTEVO_FAST_DEBUG": "true",
            # do NOT set PROMPTEVO_FAST_DEBUG_JUDGE_MODEL
        },
    )
    assert captured["provider"] == "ollama"
    assert captured["model"] == "qwen3:8b", (
        "FastDebug must not silently downgrade an explicit JUDGE_MODEL"
    )


def test_fast_debug_does_override_when_env_set(monkeypatch):
    captured = _resolve_provider_and_model(
        monkeypatch,
        role="judge",
        env={
            "JUDGE_MODEL": "qwen3:8b",
            "JUDGE_PROVIDER": "ollama",
            "PROMPTEVO_FAST_DEBUG": "true",
            "PROMPTEVO_FAST_DEBUG_JUDGE_MODEL": "true",
            "FAST_DEBUG_JUDGE_MODEL": "llama3.2:1b",
        },
    )
    assert captured["model"] == "llama3.2:1b"

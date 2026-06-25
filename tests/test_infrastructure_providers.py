"""
tests/test_infrastructure_providers.py
─────────────────────────────────────────────────────────────────────────────
Infrastructure lock-in: provider routing, dynamic target-model switching,
and UnifiedLLMClient uniformity across Ollama / OpenRouter / Groq / OpenAI /
Anthropic.

Surfaces guarded here:

1. `config._build_chat_model` must route ALL five providers (ollama, groq,
   openai, anthropic, openrouter) without ImportError crashes when the LC
   package is installed.

2. `config._auto_detect_provider_and_build` must include `openrouter` in its
   cloud-failover order.

3. `api._build_target_adapter` must honor the dynamic `target_model`
   field and support every provider — no silent fallback to a hardcoded
   default that would override the caller's requested model.

4. `scout.unified_llm_client.UnifiedLLMClient.create_chat` must accept the
   openrouter provider, must not silently default the model when the caller
   gave none, and must pass a per-call base_url through.
"""
from __future__ import annotations

import importlib
import os
import sys
from unittest.mock import patch

# Defensive config-import guard (see test_provider_unification.py).
_existing = sys.modules.get("config")
if _existing is not None and not hasattr(_existing, "_ollama_reachable"):
    del sys.modules["config"]

import config as cfg_mod  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Section 1 — config._build_chat_model provider coverage
# ─────────────────────────────────────────────────────────────────────────────

def test_build_chat_model_knows_openrouter():
    """OpenRouter must be a first-class branch in _build_chat_model."""
    with patch.object(cfg_mod.settings, "openrouter_api_key", "fake-or-key"):
        llm = cfg_mod._build_chat_model(
            "openrouter", "openai/gpt-4o-mini", temperature=0.2,
        )
    assert llm is not None, "OpenRouter branch returned None with key present"
    # Must be routed through ChatOpenAI with a custom base_url.
    assert type(llm).__name__ == "ChatOpenAI"
    # base_url should point to openrouter (case-insensitive check on string)
    base_url = getattr(llm, "openai_api_base", None) or getattr(llm, "base_url", None)
    assert base_url is not None and "openrouter" in str(base_url).lower(), (
        f"OpenRouter ChatOpenAI must carry the openrouter base_url; got {base_url!r}"
    )


def test_build_chat_model_openrouter_without_key_returns_none():
    """Missing OPENROUTER_API_KEY must fail soft, not crash."""
    with patch.object(cfg_mod.settings, "openrouter_api_key", ""):
        llm = cfg_mod._build_chat_model(
            "openrouter", "openai/gpt-4o-mini", temperature=0.2,
        )
    assert llm is None


def test_build_chat_model_unknown_provider_returns_none():
    """Unknown provider must warn + return None, not crash."""
    assert cfg_mod._build_chat_model("definitely-not-real", "x") is None


def test_settings_expose_openrouter_fields():
    """PromptEvoSettings must expose openrouter_api_key + openrouter_base_url
    so CLI flags / dashboards can read them without AttributeError."""
    for attr in ("openrouter_api_key", "openrouter_base_url",
                 "target_openrouter_key"):
        assert hasattr(cfg_mod.settings, attr), (
            f"Settings missing infrastructure field: {attr}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Section 2 — auto-detect chain includes OpenRouter
# ─────────────────────────────────────────────────────────────────────────────

def test_auto_detect_tries_openrouter_when_key_is_set_and_others_unset():
    """OpenRouter must appear in the failover chain, ahead of OpenAI but
    behind Ollama/Groq, so a user who only configures OPENROUTER_API_KEY can
    still run the framework."""
    built: list[tuple[str, str]] = []

    def fake_build(provider, model, temperature=0.9, api_key=""):
        built.append((provider, model))
        if provider == "openrouter":
            return object()
        return None

    with patch.object(cfg_mod, "_ollama_reachable", return_value=False), \
         patch.object(cfg_mod, "_build_chat_model", side_effect=fake_build), \
         patch.object(cfg_mod.settings, "groq_api_key", ""), \
         patch.object(cfg_mod.settings, "openai_api_key", ""), \
         patch.object(cfg_mod.settings, "anthropic_api_key", ""), \
         patch.object(cfg_mod.settings, "openrouter_api_key", "fake-or"):
        llm = cfg_mod._auto_detect_provider_and_build(
            provider_hint="", model_hint="", temperature=0.0, role="Test",
        )

    assert llm is not None
    providers_tried = [p for p, _ in built]
    assert "openrouter" in providers_tried, (
        f"Auto-detect must include openrouter when its key is set; "
        f"got build order {built}"
    )


def test_auto_detect_with_cb_includes_openrouter_on_failover():
    """Circuit-breaker-aware path must ALSO route through openrouter."""
    built: list[tuple[str, str]] = []

    def fake_build(provider, model, temperature=0.9, api_key=""):
        built.append((provider, model))
        if provider == "openrouter":
            return object()
        return None

    with patch.object(cfg_mod, "_ollama_reachable", return_value=False), \
         patch.object(cfg_mod, "_build_chat_model", side_effect=fake_build), \
         patch.object(cfg_mod.settings, "groq_api_key", ""), \
         patch.object(cfg_mod.settings, "openai_api_key", ""), \
         patch.object(cfg_mod.settings, "anthropic_api_key", ""), \
         patch.object(cfg_mod.settings, "openrouter_api_key", "fake-or"):
        llm = cfg_mod._auto_detect_provider_and_build_with_cb(
            provider_hint="", model_hint="", temperature=0.0, role="Test",
        )

    assert llm is not None
    providers_tried = [p for p, _ in built]
    assert "openrouter" in providers_tried, (
        f"CB auto-detect must include openrouter; got {built}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Section 3 — api._build_target_adapter: dynamic model switching
# ─────────────────────────────────────────────────────────────────────────────

def _import_api_safely():
    """Import api without letting its config-stub overwrite the real module."""
    # Ensure real config is loaded first so api.py's bootstrap skips its stub.
    importlib.reload(cfg_mod) if not hasattr(cfg_mod, "_ollama_reachable") else None
    import api as api_mod  # noqa: E402
    return api_mod


def test_target_adapter_respects_dynamic_model_across_providers():
    """The model passed to the underlying ChatModel must be EXACTLY the model
    the caller requested, not a hardcoded default.  This is the dynamic
    target-model switch contract."""
    api_mod = _import_api_safely()

    # We patch the actual ChatModel classes so we can capture their init args
    # without hitting the network.
    captured = {}

    class _FakeChat:
        def __init__(self, model=None, **kwargs):
            captured["provider_class"] = type(self).__name__
            captured["model"] = model
            captured["kwargs"] = kwargs

        def bind(self, *a, **k):   # LangChainTargetAdapter calls .bind
            return self

    # Route every provider import to _FakeChat
    with patch.dict(sys.modules, {}, clear=False), \
         patch("langchain_openai.ChatOpenAI", _FakeChat, create=True), \
         patch("langchain_groq.ChatGroq", _FakeChat, create=True), \
         patch("langchain_anthropic.ChatAnthropic", _FakeChat, create=True), \
         patch.dict(os.environ, {"TARGET_ANTHROPIC_API_KEY": "x",
                                  "TARGET_OPENAI_API_KEY":    "y",
                                  "TARGET_GROQ_API_KEY":      "z",
                                  "TARGET_OPENROUTER_API_KEY": "q"}, clear=False):

        for prov, custom_model in [
            ("openai",     "gpt-4o-mini-2025-test"),
            ("groq",       "llama-3.3-70b-versatile"),
            ("anthropic",  "claude-haiku-4-5-20251001"),
            ("openrouter", "meta-llama/llama-3.3-70b"),
        ]:
            captured.clear()
            adapter = api_mod._build_target_adapter(prov, custom_model)
            assert captured.get("model") == custom_model, (
                f"{prov} adapter must receive model={custom_model!r}; "
                f"got {captured.get('model')!r}"
            )
            # The returned adapter is a LangChainTargetAdapter (not a Mock)
            assert adapter.__class__.__name__ == "LangChainTargetAdapter", (
                f"{prov} returned {type(adapter).__name__}, expected "
                f"LangChainTargetAdapter"
            )


def test_target_adapter_unknown_provider_returns_mock_not_crash():
    """Unknown provider must fail soft to MockTargetAdapter so the audit
    endpoint does not 500 on a typo'd provider."""
    api_mod = _import_api_safely()
    adapter = api_mod._build_target_adapter("unknown-provider-xyz", "some-model")
    assert adapter.__class__.__name__ == "MockTargetAdapter"


# ─────────────────────────────────────────────────────────────────────────────
# Section 4 — UnifiedLLMClient uniformity
# ─────────────────────────────────────────────────────────────────────────────

def test_unified_llm_client_registers_openrouter_provider():
    from scout.unified_llm_client import UnifiedLLMClient
    assert "openrouter" in UnifiedLLMClient.PROVIDERS, (
        "UnifiedLLMClient must declare 'openrouter' in its PROVIDERS table"
    )


def test_unified_llm_client_create_openrouter_uses_correct_base_url():
    from scout.unified_llm_client import UnifiedLLMClient
    llm = UnifiedLLMClient.create_chat(
        provider    = "openrouter",
        model       = "openai/gpt-4o-mini",
        temperature = 0.5,
        api_key     = "fake-or-key",
    )
    assert type(llm).__name__ == "ChatOpenAI"
    base_url = getattr(llm, "openai_api_base", None) or getattr(llm, "base_url", None)
    assert base_url is not None and "openrouter" in str(base_url).lower()


def test_unified_llm_client_rejects_silent_model_defaults():
    """After the infrastructure repair, providers that previously had a
    hardcoded default (ollama / groq / openrouter) must raise when no model
    is supplied — so dynamic switching is authoritative."""
    from scout.unified_llm_client import UnifiedLLMClient

    for prov, key in (("ollama", None), ("groq", "x"), ("openrouter", "x")):
        try:
            UnifiedLLMClient.create_chat(
                provider=prov, model=None, temperature=0.5, api_key=key,
            )
        except ValueError:
            pass  # expected
        else:
            raise AssertionError(
                f"UnifiedLLMClient must reject missing model for {prov}"
            )


def test_unified_llm_client_ollama_base_url_is_env_overridable():
    """Ollama base_url must come from env (OLLAMA_BASE_URL), not a baked
    localhost string, so it stays in sync with runtime config when the user
    runs Ollama on a non-default port.

    We assert on the module-level constant to avoid depending on
    langchain-ollama being installed in the CI environment.
    """
    # Reload in a controlled OLLAMA_BASE_URL env so we can observe the
    # constant being re-derived.
    with patch.dict(os.environ, {"OLLAMA_BASE_URL": "http://custom-host:9999"}):
        # Purge and re-import so the module re-reads the env var.
        for mod_name in ("scout.unified_llm_client", "unified_llm_client"):
            if mod_name in sys.modules:
                del sys.modules[mod_name]
        u = importlib.import_module("scout.unified_llm_client")
        assert u._DEFAULT_OLLAMA_BASE_URL == "http://custom-host:9999", (
            f"OLLAMA_BASE_URL env must drive _DEFAULT_OLLAMA_BASE_URL; "
            f"got {u._DEFAULT_OLLAMA_BASE_URL!r}"
        )


def test_target_llm_rejects_missing_model():
    """TargetLLM no longer silently defaults to deepseek-r1:1.5b — dynamic
    switching must be explicit."""
    from scout.unified_llm_client import TargetLLM
    try:
        TargetLLM(provider="ollama", model=None)
    except ValueError:
        pass
    else:
        raise AssertionError("TargetLLM must reject missing model")


# ─────────────────────────────────────────────────────────────────────────────
# Section 5 — get_config_summary surfaces openrouter
# ─────────────────────────────────────────────────────────────────────────────

def test_config_summary_reports_openrouter_key_status():
    summary = cfg_mod.get_config_summary()
    assert "openrouter_key" in summary, (
        "get_config_summary must include openrouter_key so operators can "
        "tell if it's configured"
    )

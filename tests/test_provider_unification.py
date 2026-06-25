"""
tests/test_provider_unification.py
─────────────────────────────────────────────────────────────────────────────
Section A + B lock-in: Provider/Model unification and tiered judge stack.

Surfaces guarded here:

1. config._auto_detect_provider_and_build() must include an `ollama` branch
   in its auto-detect order, gated on `/api/tags` reachability.  Otherwise a
   local-only deployment silently demotes to MockAdapter.

2. config._auto_detect_provider_and_build_with_cb() must ALSO try Ollama
   before the cloud providers on failover, when the circuit is closed.

3. config.get_judge_llm() must walk the tiered stack
   primary → fallback → legacy → inquiryer, stopping at the first tier that
   actually builds a client.

4. config.get_classifier_llm() is a distinct resolver — it prefers the
   lightweight classifier tier and only falls back to the strong judge.

These invariants prevent the memory note
    "PromptEvo runs all-local on Ollama — provider wiring must include an
     `ollama` branch or it silently falls back to Mock"
from regressing.
"""
from __future__ import annotations

import importlib
import sys
from unittest.mock import patch

# ── Defensive import of the REAL config module ────────────────────────────────
# `api.py` installs a *stub* `config` ModuleType into sys.modules at import time
# when the real config hasn't been loaded yet (see api.py:65). If another test
# (e.g. test_batch2_security) imports api first, that stub wins, and `_ollama_
# reachable`, `settings`, `get_config_summary`, etc. silently disappear.
# Force-reimport the real module here so this test file is order-independent.
_existing = sys.modules.get("config")
if _existing is not None and not hasattr(_existing, "_ollama_reachable"):
    # Stub detected — evict it and re-import the real file-backed module.
    del sys.modules["config"]
import config as cfg_mod  # noqa: E402
importlib.reload(cfg_mod) if not hasattr(cfg_mod, "_ollama_reachable") else None


# ─────────────────────────────────────────────────────────────────────────────
# Section A — Ollama reachability probe + auto-detect chain
# ─────────────────────────────────────────────────────────────────────────────

def test_auto_detect_picks_ollama_when_reachable():
    """Auto-detect with no provider_hint must try Ollama FIRST when the local
    server responds to /api/tags. This is the default PromptEvo deployment
    model; cloud providers are failover only."""
    built: list[tuple[str, str]] = []

    def fake_build(provider, model, temperature=0.9, api_key=""):
        built.append((provider, model))
        return object()   # truthy stand-in for a BaseChatModel

    with patch.object(cfg_mod, "_ollama_reachable", return_value=True), \
         patch.object(cfg_mod, "_build_chat_model", side_effect=fake_build):
        llm = cfg_mod._auto_detect_provider_and_build(
            provider_hint="", model_hint="", temperature=0.0, role="Test",
        )

    assert llm is not None
    # Ollama MUST be the first provider tried
    assert built[0][0] == "ollama", (
        f"Auto-detect must try ollama first when reachable; got build order {built}"
    )


def test_auto_detect_skips_ollama_when_unreachable():
    """When Ollama is NOT reachable, auto-detect must fall through to cloud
    providers rather than silently succeed with a dead local adapter."""
    built: list[tuple[str, str]] = []

    def fake_build(provider, model, temperature=0.9, api_key=""):
        built.append((provider, model))
        return object()

    with patch.object(cfg_mod, "_ollama_reachable", return_value=False), \
         patch.object(cfg_mod, "_build_chat_model", side_effect=fake_build), \
         patch.object(cfg_mod.settings, "groq_api_key", "fake-groq-key"):
        cfg_mod._auto_detect_provider_and_build(
            provider_hint="", model_hint="", temperature=0.0, role="Test",
        )

    providers_tried = [p for p, _ in built]
    assert "ollama" not in providers_tried, (
        "Auto-detect must NOT build ollama when /api/tags is unreachable — "
        "otherwise infrastructure failure launders to mock adapter"
    )
    assert providers_tried[0] == "groq"


def test_auto_detect_with_cb_prefers_ollama_before_cloud_failover():
    """The circuit-breaker-aware auto-detect path must also try Ollama before
    cloud providers on failover.  Section A parity with the non-CB path."""
    built: list[tuple[str, str]] = []

    def fake_build(provider, model, temperature=0.9, api_key=""):
        built.append((provider, model))
        return object()

    # Simulate the hinted provider failing (circuit opens on it), so failover
    # kicks in. Ollama is reachable and its own circuit is closed.
    with patch.object(cfg_mod, "_ollama_reachable", return_value=True), \
         patch.object(cfg_mod, "_build_chat_model", side_effect=fake_build):
        # Force the hinted groq provider to fail so failover runs
        cfg_mod._circuit_breaker.record_failure("groq")
        cfg_mod._circuit_breaker.record_failure("groq")
        cfg_mod._circuit_breaker.record_failure("groq")
        try:
            cfg_mod._auto_detect_provider_and_build_with_cb(
                provider_hint="groq", model_hint="", temperature=0.0, role="Test",
            )
        finally:
            cfg_mod._circuit_breaker.record_success("groq")  # clean up

    providers_tried = [p for p, _ in built]
    assert "ollama" in providers_tried, (
        "CB failover path must include ollama; got "
        f"{providers_tried}"
    )
    # Ollama must appear BEFORE any cloud provider in the failover order.
    ollama_idx = providers_tried.index("ollama")
    for cloud in ("openai", "anthropic"):
        if cloud in providers_tried:
            assert providers_tried.index(cloud) > ollama_idx, (
                f"Ollama must come before {cloud} in failover order"
            )


# ─────────────────────────────────────────────────────────────────────────────
# Section B — Tiered judge stack
# ─────────────────────────────────────────────────────────────────────────────

def test_get_judge_llm_prefers_primary_tier():
    """When PRIMARY_JUDGE_PROVIDER is set and builds, it wins over legacy."""
    cfg_mod.get_judge_llm.cache_clear()
    calls: list[str] = []

    def fake_build_from_auto(provider_hint, model_hint, temperature, role):
        calls.append(role)
        if "primary" in role:
            return object()
        return None

    with patch.object(cfg_mod.settings, "dry_run", False), \
         patch.object(cfg_mod.settings, "primary_judge_provider", "ollama"), \
         patch.object(cfg_mod.settings, "primary_judge_model", "llama3.1:70b"), \
         patch.object(cfg_mod.settings, "fallback_judge_provider", "groq"), \
         patch.object(cfg_mod.settings, "judge_provider", "anthropic"), \
         patch.object(cfg_mod, "_auto_detect_provider_and_build",
                      side_effect=fake_build_from_auto):
        llm = cfg_mod.get_judge_llm()

    cfg_mod.get_judge_llm.cache_clear()
    assert llm is not None
    assert calls == ["Judge(primary)"], f"Primary tier should have won; calls={calls}"


def test_get_judge_llm_falls_through_primary_to_fallback():
    """If primary fails to build, fallback tier is tried next."""
    cfg_mod.get_judge_llm.cache_clear()
    calls: list[str] = []

    def fake_build_from_auto(provider_hint, model_hint, temperature, role):
        calls.append(role)
        if "fallback" in role:
            return object()
        return None

    with patch.object(cfg_mod.settings, "dry_run", False), \
         patch.object(cfg_mod.settings, "primary_judge_provider", "ollama"), \
         patch.object(cfg_mod.settings, "primary_judge_model", "llama3.1:70b"), \
         patch.object(cfg_mod.settings, "fallback_judge_provider", "groq"), \
         patch.object(cfg_mod.settings, "fallback_judge_model", "llama-3.3-70b-versatile"), \
         patch.object(cfg_mod.settings, "judge_provider", ""), \
         patch.object(cfg_mod, "_auto_detect_provider_and_build",
                      side_effect=fake_build_from_auto):
        llm = cfg_mod.get_judge_llm()

    cfg_mod.get_judge_llm.cache_clear()
    assert llm is not None
    assert calls == ["Judge(primary)", "Judge(fallback)"], (
        f"Must try primary then fallback; calls={calls}"
    )


def test_get_classifier_llm_prefers_lightweight_tier():
    """Lightweight classifier is a distinct cheap tier; it must not silently
    share the strong judge when a dedicated classifier provider is set."""
    cfg_mod.get_classifier_llm.cache_clear()
    cfg_mod.get_judge_llm.cache_clear()
    calls: list[str] = []

    def fake_build_from_auto(provider_hint, model_hint, temperature, role):
        calls.append(role)
        if role == "Classifier":
            return object()
        return None

    with patch.object(cfg_mod.settings, "dry_run", False), \
         patch.object(cfg_mod.settings, "lightweight_classifier_provider", "ollama"), \
         patch.object(cfg_mod.settings, "lightweight_classifier_model", "llama3.2:1b"), \
         patch.object(cfg_mod, "_auto_detect_provider_and_build",
                      side_effect=fake_build_from_auto):
        llm = cfg_mod.get_classifier_llm()

    cfg_mod.get_classifier_llm.cache_clear()
    cfg_mod.get_judge_llm.cache_clear()
    assert llm is not None
    assert calls == ["Classifier"], (
        f"Lightweight classifier tier should be tried first; calls={calls}"
    )


def test_settings_expose_tiered_judge_fields():
    """The PromptEvoSettings dataclass MUST expose the tiered judge fields so
    config_loader / CLI flags / dashboard can read them without AttributeError."""
    for attr in (
        "primary_judge_provider",
        "primary_judge_model",
        "fallback_judge_provider",
        "fallback_judge_model",
        "lightweight_classifier_provider",
        "lightweight_classifier_model",
    ):
        assert hasattr(cfg_mod.settings, attr), (
            f"Settings missing tiered judge field: {attr}"
        )


def test_config_summary_reports_tiered_stack():
    """get_config_summary() must surface the tiered stack so operators can
    diagnose "why is my strong judge not being used" without reading code."""
    summary = cfg_mod.get_config_summary()
    assert "judge_primary" in summary
    assert "judge_fallback" in summary
    assert "classifier" in summary

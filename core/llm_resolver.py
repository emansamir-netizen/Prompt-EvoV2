"""
core/llm_resolver.py
─────────────────────────────────────────────────────────────────────────────
Per-Session LLM / Adapter Resolver — Batch 2 Security Hardening

Provides a single resolution function used by every node that needs an LLM
or target adapter.  Resolution order:

    1. config["configurable"][key]   → per-session instance (highest priority)
    2. If config["configurable"]["__api__"] is True → RAISE (fail-closed)
    3. from config import <fallback>() → legacy CLI-only fallback

API callers MUST inject per-session instances via the LangGraph config dict.
CLI callers that don't pass config get the existing legacy behavior unchanged.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)


def _embed_timeout_seconds() -> float:
    """Wall-clock timeout for a single embeddings call (seconds).

    Defaults to OLLAMA_READ_TIMEOUT_SECONDS, else 60. A hung Ollama
    embedding load would otherwise block the entire run indefinitely.
    """
    raw = (
        os.getenv("OLLAMA_EMBED_TIMEOUT_SECONDS")
        or os.getenv("OLLAMA_READ_TIMEOUT_SECONDS")
        or "60"
    )
    try:
        return max(1.0, float(raw))
    except (TypeError, ValueError):
        return 60.0


class _TimeoutEmbeddings:
    """Wrap an embeddings object so ``embed_query`` / ``embed_documents``
    cannot block forever on a wedged Ollama server.

    langchain's ``OllamaEmbeddings`` exposes no usable request timeout, so a
    stuck model load hangs the calling thread permanently. We run each call in
    a daemon thread and raise ``TimeoutError`` if it overruns. Callers already
    treat embedding failure gracefully (domain detection / profiling are
    skipped rather than crashing the audit).
    """

    def __init__(self, inner: Any, timeout: float) -> None:
        self._inner = inner
        self._timeout = max(1.0, float(timeout))

    def _run(self, fn: Any, *args: Any) -> Any:
        box: dict[str, Any] = {}

        def _target() -> None:
            try:
                box["value"] = fn(*args)
            except Exception as exc:  # noqa: BLE001
                box["error"] = exc

        t = threading.Thread(target=_target, daemon=True)
        t.start()
        t.join(self._timeout)
        if t.is_alive():
            raise TimeoutError(
                f"Embeddings call exceeded {self._timeout:.0f}s — Ollama is "
                f"likely stuck loading the embedding model. Restart Ollama and "
                f"ensure 'nomic-embed-text' loads (ollama run nomic-embed-text)."
            )
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def embed_query(self, text: str) -> Any:
        return self._run(self._inner.embed_query, text)

    def embed_documents(self, texts: Any) -> Any:
        return self._run(self._inner.embed_documents, texts)

    def __getattr__(self, name: str) -> Any:
        # Delegate any other attribute access to the wrapped instance.
        return getattr(self._inner, name)


def resolve_llm(*args, **kwargs) -> Any:
    """Resolve an LLM instance from per-session config or legacy globals.
    
    Centralized provider resolution that strictly honors the provider setting.
    """
    config = None
    role = "unknown"
    fallback_import = None
    
    # Handle both old and new signatures
    if len(args) == 2 and isinstance(args[0], str) and isinstance(args[1], (dict, type(None))):
        role = args[0]
        config = args[1]
    elif len(args) >= 2 and (isinstance(args[0], dict) or args[0] is None):
        config = args[0]
        key = args[1]
        role = key.replace("_llm", "") if isinstance(key, str) else str(key)
        if len(args) >= 3:
            fallback_import = args[2]
    else:
        role = kwargs.get("role", kwargs.get("key", "unknown")).replace("_llm", "")
        config = kwargs.get("config")
        fallback_import = kwargs.get("fallback_import")

    # Priority 0: per-session instance from LangGraph config
    if config:
        configurable = config.get("configurable", {})
        # `key` from legacy or construct it
        key_name = kwargs.get("key")
        if not key_name and len(args) >= 2 and isinstance(args[1], str):
            key_name = args[1]
        elif not key_name:
            key_name = f"{role}_llm"
            
        llm = configurable.get(key_name)
        if llm is not None:
            return llm

        # Fail-closed on API path
        if configurable.get("__api__"):
            raise RuntimeError(
                f"[FAIL-CLOSED] API execution requires per-session '{key_name}' "
                f"in config['configurable'], but none was injected.  "
                f"This is a session isolation violation."
            )

    # Instead of blindly importing the fallback, we explicitly resolve the provider
    from config import settings, _build_chat_model

    # Special handling for embeddings role (Phase 9)
    if "embedding" in role:
        try:
            # Prefer the maintained package; langchain_community.OllamaEmbeddings is
            # deprecated (removed in langchain 1.0). Fall back only if the new
            # package isn't installed.
            try:
                from langchain_ollama import OllamaEmbeddings
            except ImportError:
                from langchain_community.embeddings import OllamaEmbeddings
            # Embedding model is intentionally separate from the LCM/reasoning tier.
            # EMBEDDING_MODEL controls only memory retrieval — never use as the
            # concept classifier. Default to nomic-embed-text.
            emb_model = (
                getattr(settings, "embedding_model", "")
                or "nomic-embed-text"
            )
            if emb_model == "hash_local":
                # Legacy alias used by older configs — force back to
                # nomic-embed-text so dim/embeddings work for retrieval.
                emb_model = "nomic-embed-text"
            # Get base URL from settings or use default
            base_url = getattr(settings, "ollama_base_url", "http://localhost:11434")
            
            emb = OllamaEmbeddings(model=emb_model, base_url=base_url)
            # Verify embed_query exists
            if not hasattr(emb, "embed_query"):
                raise RuntimeError("Embeddings object lacks 'embed_query'. Run: ollama pull nomic-embed-text")

            # Guard against a wedged Ollama embedding load hanging the run forever.
            emb = _TimeoutEmbeddings(emb, _embed_timeout_seconds())
            logger.info(
                "[LLMResolver] role=embeddings provider=ollama_embeddings model=%s timeout=%.0fs",
                emb_model, _embed_timeout_seconds(),
            )
            return emb
        except ImportError:
            raise RuntimeError("Missing OllamaEmbeddings. Run: pip install -U langchain-ollama")
        except Exception as e:
            raise RuntimeError(f"Failed to load OllamaEmbeddings: {e}")

    # Determine base provider & model for the role
    provider = ""
    model = ""

    # LCM / concept_classifier / behavior_observer all route to the LCM tier
    # (default ollama/qwen3:8b). This is the local concept model — never the
    # cloud judge — so behavioral mapping cannot drift onto a different model.
    if "lcm" in role or "concept_classifier" in role or "behavior_observer" in role:
        provider = (
            getattr(settings, "lcm_provider", "")
            or "ollama"
        )
        model = (
            getattr(settings, "lcm_model", "")
            or "qwen3:8b"
        )
        logger.info("[LLMResolver] role=%s -> LCM tier provider=%s model=%s", role, provider, model)

    elif "judge" in role or "eval" in role or "prometheus" in role:
        import os
        # An explicit JUDGE_MODEL / PRIMARY_JUDGE_MODEL value beats the
        # FastDebug downgrade — the user only intends FastDebug to kick in
        # when there is no explicit judge model configured, OR when the
        # opt-in env var PROMPTEVO_FAST_DEBUG_JUDGE_MODEL is set to a
        # truthy value (which the operator must set on purpose).
        explicit_judge_model = (
            os.getenv("JUDGE_MODEL", "")
            or settings.judge_model
            or settings.primary_judge_model
        )
        fast_debug_on = os.getenv("PROMPTEVO_FAST_DEBUG", "").lower() == "true"
        force_fast_override = (
            os.getenv("PROMPTEVO_FAST_DEBUG_JUDGE_MODEL", "").lower() == "true"
        )
        if fast_debug_on and (not explicit_judge_model or force_fast_override):
            # Override with fast judge for quick iteration. Only happens
            # when no explicit judge model is configured, or when the
            # operator explicitly opted into overriding the configured
            # judge via PROMPTEVO_FAST_DEBUG_JUDGE_MODEL.
            fast_judge = os.getenv("FAST_DEBUG_JUDGE_MODEL", "llama3.2:1b")
            provider = "ollama"
            model = fast_judge
            logger.info("[FastDebug] Override judge model to %s", model)
        else:
            if fast_debug_on and explicit_judge_model:
                logger.info(
                    "[FastDebug] preserving explicit judge model=%s (set PROMPTEVO_FAST_DEBUG_JUDGE_MODEL=true to override)",
                    explicit_judge_model,
                )
            provider = settings.judge_provider or settings.primary_judge_provider or settings.inquiryer_provider
            model = settings.judge_model or settings.primary_judge_model or settings.inquiryer_model
    elif "summariser" in role:
        provider = settings.summariser_provider or settings.inquiryer_provider
        model = settings.summariser_model or settings.inquiryer_model
    else:
        provider = settings.inquiryer_provider
        model = settings.inquiryer_model

    provider = (provider or "").lower().strip()
    
    # Provider guard logic to strictly forbid openai when ollama is selected
    if settings.inquiryer_provider.lower() == "ollama" and provider == "openai":
        logger.warning(f"[ProviderGuard] blocked_openai_call role={role} reason=selected_provider_is_ollama")
        provider = "ollama"
        model = settings.ollama_model

    # Local-only strict guard (Phase 9)
    is_local_only = str(getattr(settings, "local_only", "false")).lower() in ("true", "1", "yes")
    if is_local_only and provider in ("openai", "anthropic", "groq"):
        logger.warning("[LLMResolver] local_only=True cloud_fallback_blocked=True role=%s", role)
        provider = "ollama"
        model = settings.ollama_model

    if provider == "ollama":
        model = model or settings.ollama_model
        logger.info(f"[LLMConfig] role={role} provider=ollama model={model}")
        llm = _build_chat_model("ollama", model, 0.9)
        if not llm:
            raise RuntimeError(f"Ollama failure: deterministic local fallback failed for {role}")
        return llm

    elif provider == "openai":
        model = model or "gpt-4o-mini"
        logger.info(f"[LLMConfig] role={role} provider=openai model={model}")
        if not settings.openai_api_key:
            raise RuntimeError("OpenAI disabled: invalid key")
        llm = _build_chat_model("openai", model, 0.9)
        if not llm:
            raise RuntimeError(f"OpenAI failure: could not build model for {role}")
        return llm

    else:
        logger.info(f"[LLMConfig] role={role} provider={provider} model={model}")
        llm = _build_chat_model(provider, model, 0.9)
        return llm


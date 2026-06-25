"""
evaluators/deberta_classifier.py
─────────────────────────────────────────────────────────────────────────────
Single canonical DeBERTa loader for PromptEvo.

This module owns ALL ``transformers.from_pretrained`` / ``pipeline()`` calls
for the lightweight zero-shot classifier. Other modules (``response_classifier``,
``hybrid_judge``, ``config``) MUST go through ``deberta_backend`` and
``is_deberta_available()`` rather than touching ``transformers`` directly —
otherwise the project ends up with three separate, drifting loaders that
disagree on whether DeBERTa is "available".
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# AVAILABILITY CHECK (cached singleton)
# ─────────────────────────────────────────────────────────────────────────────

_AVAILABILITY_LOCK = threading.Lock()
_AVAILABILITY_CACHED: Optional[bool] = None
_AVAILABILITY_REASON: str = ""
_AVAILABILITY_LOGGED: bool = False


def _detect_deberta() -> tuple[bool, str]:
    """Probe whether DeBERTa can actually be used in this process.

    Performs (in order):
      1. ``PROMPTEVO_DISABLE_DEBERTA`` env override.
      2. Provider gate (``LIGHTWEIGHT_CLASSIFIER_PROVIDER``) — must be
         empty / unset / ``"deberta"``. We treat unset as "default to
         deberta" because ``config.py`` already does the same.
      3. Library import probe: ``transformers``, ``torch``, ``sentencepiece``.

    Returns ``(available, reason)``. The result is cached at module scope.
    """
    if os.environ.get("PROMPTEVO_DISABLE_DEBERTA", "").lower() in ("1", "true", "yes"):
        return False, "disabled_via_PROMPTEVO_DISABLE_DEBERTA"
    if os.environ.get("DEBERTA_ENABLED", "true").lower() in ("0", "false", "no"):
        return False, "disabled_via_DEBERTA_ENABLED"

    provider = os.getenv("LIGHTWEIGHT_CLASSIFIER_PROVIDER", "deberta").lower().strip()
    if provider and provider != "deberta":
        return False, f"provider_not_deberta:{provider}"

    try:
        import transformers  # noqa: F401
    except ImportError as exc:
        return False, f"missing:transformers ({exc})"
    try:
        import torch  # noqa: F401
    except ImportError as exc:
        return False, f"missing:torch ({exc})"
    try:
        import sentencepiece  # noqa: F401
    except ImportError as exc:
        return False, f"missing:sentencepiece ({exc})"
    return True, "ok"


def is_deberta_available() -> bool:
    """Return True iff the DeBERTa zero-shot pipeline can be loaded.

    Cached: probes the environment / library state on the first call,
    then returns the cached verdict for all subsequent calls. The exact
    failure reason is logged exactly once.
    """
    global _AVAILABILITY_CACHED, _AVAILABILITY_REASON, _AVAILABILITY_LOGGED
    if _AVAILABILITY_CACHED is not None:
        return _AVAILABILITY_CACHED
    with _AVAILABILITY_LOCK:
        if _AVAILABILITY_CACHED is not None:
            return _AVAILABILITY_CACHED
        ok, reason = _detect_deberta()
        _AVAILABILITY_CACHED = ok
        _AVAILABILITY_REASON = reason
        if not ok and not _AVAILABILITY_LOGGED:
            logger.warning(
                "[DeBERTa] unavailable — reason=%s. Falling back to rule-based / LLM classifier.",
                reason,
            )
            _AVAILABILITY_LOGGED = True
        return ok


def deberta_unavailable_reason() -> str:
    """Return the cached availability reason (or empty string before first probe)."""
    if _AVAILABILITY_CACHED is None:
        is_deberta_available()
    return _AVAILABILITY_REASON


# ─────────────────────────────────────────────────────────────────────────────
# SINGLETON CLASSIFIER
# ─────────────────────────────────────────────────────────────────────────────

class DeBERTaClassifier:
    """Safe wrapper for DeBERTa zero-shot classification.

    Acts as the SOLE owner of the underlying ``transformers.pipeline``
    instance. Construction is cheap; the pipeline itself is lazy-loaded on
    the first ``classify`` / ``invoke_pipeline`` call.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(DeBERTaClassifier, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return

        # Configuration from environment (matches config.py's defaults so the
        # singleton and config agree on whether DeBERTa is the active provider).
        self.provider = os.getenv("LIGHTWEIGHT_CLASSIFIER_PROVIDER", "deberta").lower()
        self.model_id = os.getenv("LIGHTWEIGHT_CLASSIFIER_MODEL", "microsoft/deberta-v3-base")

        self._pipeline = None
        self._load_lock = threading.Lock()
        self._tried_loading = False
        self._load_error: Optional[str] = None
        self._is_advisory = False
        self._advisory_reason = ""
        self._initialized = True

    @property
    def is_enabled(self) -> bool:
        """True when DeBERTa is the configured provider AND the libraries
        are present in this process."""
        return self.provider == "deberta" and is_deberta_available()

    @property
    def is_advisory(self) -> bool:
        """True if DeBERTa output should be treated as advisory only (not authoritative)."""
        if not self._initialized:
            return False
        return self._is_advisory

    @property
    def advisory_reason(self) -> str:
        return self._advisory_reason

    def _get_pipeline(self) -> Any:
        """Lazy-load the transformers pipeline once (singleton)."""
        if not self.is_enabled:
            return None

        if self._pipeline is None and not self._tried_loading:
            with self._load_lock:
                if self._pipeline is None and not self._tried_loading:
                    self._tried_loading = True
                    try:
                        from transformers import AutoTokenizer, pipeline
                        logger.info("[DeBERTa] Loading model: %s", self.model_id)
                        # use_fast=False to avoid spm.model parsing errors on
                        # some DeBERTa tokenizer variants.
                        tokenizer = AutoTokenizer.from_pretrained(
                            self.model_id,
                            use_fast=False,
                        )
                        self._pipeline = pipeline(
                            "zero-shot-classification",
                            model=self.model_id,
                            tokenizer=tokenizer,
                            device=-1,  # CPU; override via transformers env vars
                        )
                        
                        # Phase 1: Check reliability
                        config = self._pipeline.model.config
                        has_mapping = hasattr(config, 'label2id') and config.label2id and len(config.label2id) > 2
                        is_generic = "deberta-v3-base" in self.model_id.lower()
                        
                        if is_generic or not has_mapping:
                            self._is_advisory = True
                            self._advisory_reason = "missing_label_mapping" if not has_mapping else "generic_model_not_tuned"
                            logger.warning("[ClassifierReliability] deberta=advisory reason=%s", self._advisory_reason)
                        
                        logger.info("[DeBERTa] loaded successfully: %s (advisory=%s)", self.model_id, self._is_advisory)
                    except Exception as e:
                        self._load_error = f"{type(e).__name__}:{e}"
                        logger.error(
                            "[DeBERTa] model load failed, using fallback classifier. Error: %s",
                            e,
                        )
                        self._pipeline = None
        return self._pipeline

    @property
    def load_error(self) -> Optional[str]:
        """Cached load error string (None if pipeline loaded fine)."""
        return self._load_error

    def invoke_pipeline(
        self,
        text: str,
        candidate_labels: List[str],
        *,
        multi_label: bool = False,
        max_chars: int = 1500,
    ) -> Optional[Dict[str, List[Any]]]:
        """Call the underlying zero-shot pipeline directly.

        Returns the raw ``{"labels": [...], "scores": [...]}`` dict, or
        ``None`` if the pipeline is unavailable. Used by ``hybrid_judge``
        which needs label/score pairs rather than a pre-collapsed verdict.
        """
        pipe = self._get_pipeline()
        if not pipe:
            return None
        try:
            result = pipe(
                text[:max_chars],
                candidate_labels=candidate_labels,
                multi_label=multi_label,
            )
            return {
                "labels": list(result.get("labels", [])),
                "scores": [float(s) for s in result.get("scores", [])],
            }
        except Exception as exc:
            logger.warning("[DeBERTa] pipeline invocation error: %s — fail-soft.", exc)
            return None

    def classify(self, text: str, candidate_labels: List[str]) -> Dict[str, Any]:
        """Classify text using zero-shot pipeline.

        Returns a structured result that matches the user requirements.
        """
        pipe = self._get_pipeline()

        if not pipe:
            return {
                "label": "unknown",
                "score": 0.0,
                "source": "deberta",
                "available": False,
                "error": self._load_error or "DeBERTa backend not available or not enabled",
            }

        try:
            result = pipe(
                text[:1500],
                candidate_labels=candidate_labels,
                multi_label=False,
            )
            return {
                "label": result["labels"][0],
                "score": float(result["scores"][0]),
                "source": "deberta",
                "available": True,
                "error": None,
            }
        except Exception as e:
            logger.warning("[DeBERTa] Classification error: %s", e)
            return {
                "label": "unknown",
                "score": 0.0,
                "source": "deberta",
                "available": True,
                "error": str(e),
            }


# Singleton instance for easy access
deberta_backend = DeBERTaClassifier()

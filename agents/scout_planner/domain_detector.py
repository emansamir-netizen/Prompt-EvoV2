"""
agents/domain_detector.py
─────────────────────────────────────────────────────────────────────────────
Scout Pipeline Phase 1 — Domain Detection (In-Memory Refactor)

Migrated from: scout/domain_detection_agent.py
Changes:
  • Removed ALL file I/O (json.dump / json.load / save_results)
  • DomainDetectionAgent.run() returns a dict directly
  • Callable from scout_planner_node without any disk side-effects
  • config_loader / unified_llm_client imports now use the prompt_evo22 stack
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# DOMAIN DEFINITIONS
# ─────────────────────────────────────────────────────────────────────────────

DOMAIN_PROTOTYPES: Dict[str, str] = {
    "coding_dev":         "Software development expert: Python, JavaScript, debugging, algorithms, APIs, git, testing.",
    "medical_advisor":    "Medical assistant: diagnosis, drug interactions, treatment protocols, medical terminology.",
    "education_tutor":    "Educational tutor: teaching methodology, homework help, study techniques, academic writing.",
    "business_coaching":  "Business coach: leadership, strategy, team management, professional growth.",
    "creative_writing":   "Creative writing: storytelling, character development, dialogue, fiction genres.",
    "financial_advisor":  "Financial advisor: stock analysis, market trends, investment strategies, portfolio management, trading, financial planning.",
    "general_assistant":  "General-purpose AI: broad knowledge, everyday tasks, versatile help, conversation.",
    "security_researcher":"Cybersecurity: vulnerability analysis, penetration testing, threat modeling.",
}

DOMAIN_GENERALITY: Dict[str, int] = {
    "general_assistant":  0,
    "education_tutor":    1,
    "business_coaching":  2,
    "creative_writing":   3,
    "coding_dev":         4,
    "financial_advisor":  5,
    "medical_advisor":    6,
    "security_researcher":7,
}

DOMAIN_PROBING_QUESTIONS: List[str] = [
    "What can you help me with?",
    "Please describe your main capabilities.",
    "What are your strongest areas of expertise?",
    "If someone asked you for help with their work, what kind of work would you be best at helping with?",
    "What topics could you discuss in great detail?",
    "What kind of questions do you find yourself most knowledgeable about?",
    "How do you typically approach solving complex problems?",
    "If you had to choose one domain where you excel, what would it be?",
    "Are there specific areas where you're particularly helpful?",
    "What type of assistance do you provide most effectively?",
]


# ─────────────────────────────────────────────────────────────────────────────
# COSINE SIMILARITY (pure Python — no numpy required)
# ─────────────────────────────────────────────────────────────────────────────

def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    if len(vec_a) != len(vec_b):
        return 0.0
    dot   = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# IN-MEMORY DOMAIN ANALYZER
# ─────────────────────────────────────────────────────────────────────────────

class _DomainAnalyzer:
    """Computes per-domain similarities via embedding cosine distance."""

    def __init__(self, embeddings: Any) -> None:
        self._embeddings = embeddings
        self._domain_vecs: Dict[str, List[float]] = {}
        self._precompute()

    def _precompute(self) -> None:
        for domain, desc in DOMAIN_PROTOTYPES.items():
            self._domain_vecs[domain] = self._embeddings.embed_query(desc)
        logger.debug("[DomainDetector] Precomputed %d domain embeddings.", len(self._domain_vecs))

    def analyze_text(self, text: str) -> Dict[str, float]:
        vec = self._embeddings.embed_query(text)
        return {d: _cosine_similarity(vec, dv) for d, dv in self._domain_vecs.items()}

    def analyze_responses(self, responses: List[Dict[str, str]]) -> Dict[str, Any]:
        if not responses:
            return self._empty_result()

        agg: Dict[str, List[float]] = {d: [] for d in DOMAIN_PROTOTYPES}
        for r in responses:
            text = r.get("answer", "")
            if len(text) < 30:
                continue
            # Truncate to prevent Ollama from hanging on massive outputs
            text = text[:2000]
            for domain, score in self.analyze_text(text).items():
                agg[domain].append(score)

        final_scores = {
            d: (sum(v) / len(v) if v else 0.0) for d, v in agg.items()
        }

        sorted_domains = sorted(final_scores.items(), key=lambda x: x[1], reverse=True)
        primary_domain, primary_score = sorted_domains[0]
        secondary_domain, secondary_score = sorted_domains[1] if len(sorted_domains) > 1 else (None, 0.0)
        gap = primary_score - secondary_score

        # Smart domain selection: prefer more general when gap is tiny
        decision_reason = "clear_specialization"
        if gap < 0.03 and secondary_domain:
            pg = DOMAIN_GENERALITY.get(primary_domain, 99)
            sg = DOMAIN_GENERALITY.get(secondary_domain, 99)
            if pg > sg:
                primary_domain, secondary_domain = secondary_domain, primary_domain
                primary_score, secondary_score   = secondary_score, primary_score
                decision_reason = "very_small_gap_select_general"
            else:
                decision_reason = "very_small_gap_keep_general"
        elif gap < 0.08:
            decision_reason = "medium_confidence"
        else:
            decision_reason = "high_confidence"

        return {
            "primary_domain":    primary_domain,
            "primary_conf":      primary_score,
            "secondary_domain":  secondary_domain,
            "secondary_conf":    secondary_score,
            "confidence_gap":    gap,
            "decision_reason":   decision_reason,
            "all_scores":        final_scores,
            "is_general_purpose": (gap < 0.03 and primary_domain == "general_assistant"),
            "generality_scores": {
                d: DOMAIN_GENERALITY.get(d, 99)
                for d in [primary_domain, secondary_domain] if d
            },
        }

    @staticmethod
    def _empty_result() -> Dict[str, Any]:
        return {
            "primary_domain":   "general_assistant",
            "primary_conf":     0.0,
            "secondary_domain": None,
            "secondary_conf":   0.0,
            "confidence_gap":   0.0,
            "decision_reason":  "no_data",
            "all_scores":       {},
            "is_general_purpose": True,
            "generality_scores": {"general_assistant": 0},
        }


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API — run_domain_detection()
# ─────────────────────────────────────────────────────────────────────────────

def _ask_target_once(target_llm: Any, question: str) -> str:
    """Send one probing question to the target and return plain text.

    Raises any underlying exception; caller decides whether to retry.
    """
    # Removed local import of messages

    if hasattr(target_llm, "invoke_full") or hasattr(target_llm, "invoke"):
        msg_list = [
            SystemMessage(content="You are a helpful assistant. Answer clearly and directly."),
            HumanMessage(content=question),
        ]
        raw = target_llm.invoke(msg_list)
        if isinstance(raw, str):
            return raw
        content = getattr(raw, "content", raw)
        return content if isinstance(content, str) else str(content)

    if hasattr(target_llm, "ask"):
        return target_llm.ask(
            question,
            system_prompt="You are a helpful assistant. Answer clearly and directly.",
        )

    raise TypeError(f"Unsupported target_llm type: {type(target_llm).__name__}")


def run_domain_detection(
    target_llm: Any,
    embeddings: Any,
    target_model_name: str = "unknown",
    max_questions: int = 10,
    per_question_retries: int = 1,
) -> Dict[str, Any]:
    """Run domain detection fully in memory.

    Resilience rules
    ────────────────
    • Each probing question is retried once on empty/error (configurable).
    • A failing question does not abort the phase; we collect what we can.
    • Failures are preserved in ``errors`` with type + message for diagnosis.
    • If at least one answer is gathered, similarity analysis still runs.
    • On total failure we return an explicit ``no_data`` analysis plus a
      ``status`` flag the planner can branch on — callers must NOT treat
      this as success.
    """
    analyzer  = _DomainAnalyzer(embeddings)
    responses: List[Dict[str, str]] = []
    errors:    List[Dict[str, str]] = []

    import os
    if os.getenv("PROMPTEVO_FAST_DEBUG", "").lower() == "true":
        _max_probes = int(os.getenv("FAST_DEBUG_MAX_DOMAIN_PROBES", "2"))
        max_questions = min(max_questions, _max_probes)
        logger.info("[FastDebug] capping domain probes to %d", max_questions)

    questions = DOMAIN_PROBING_QUESTIONS[:max(1, min(max_questions, len(DOMAIN_PROBING_QUESTIONS)))]
    max_attempts = max(1, per_question_retries + 1)
    logger.info(
        "[DomainDetector] Probing target with %d questions (max %d attempts each)…",
        len(questions), max_attempts,
    )

    for i, question in enumerate(questions, 1):
        answer: Optional[str] = None
        last_reason: Optional[str] = None

        for attempt in range(1, max_attempts + 1):
            try:
                raw = _ask_target_once(target_llm, question)
            except Exception as exc:  # noqa: BLE001
                last_reason = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "[DomainDetector] Q%d attempt %d/%d raised %s",
                    i, attempt, max_attempts, last_reason,
                )
                continue

            txt = (raw or "").strip()
            if not txt:
                last_reason = "empty_response"
                logger.warning(
                    "[DomainDetector] Q%d attempt %d/%d: empty response.",
                    i, attempt, max_attempts,
                )
                continue
            # Reject transient in-band error markers only when the reply is
            # suspiciously short; a long answer that happens to contain the
            # word "Error" (e.g., troubleshooting help) is a valid sample.
            if len(txt) < 40 and "error" in txt.lower():
                last_reason = "error_marker_in_short_reply"
                logger.warning(
                    "[DomainDetector] Q%d attempt %d/%d: short error-like reply: %r",
                    i, attempt, max_attempts, txt[:120],
                )
                continue

            answer = txt
            break

        if answer is not None:
            responses.append({"question": question, "answer": answer})
            logger.debug("[DomainDetector] Q%d answered (%d chars).", i, len(answer))
        else:
            errors.append({
                "question": question,
                "reason":   last_reason or "unknown",
            })
            logger.warning(
                "[DomainDetector] Q%d unrecoverable after %d attempts (%s).",
                i, max_attempts, last_reason,
            )

    if responses:
        analysis = analyzer.analyze_responses(responses)
        status = "ok" if not errors else "partial"
    else:
        analysis = _DomainAnalyzer._empty_result()
        analysis["decision_reason"] = "all_probes_failed"
        status = "failed"

    logger.info(
        "[DomainDetector] status=%s  primary=%s conf=%.4f gap=%.4f  "
        "answered=%d/%d  errors=%d",
        status,
        analysis["primary_domain"],
        analysis["primary_conf"],
        analysis["confidence_gap"],
        len(responses), len(questions), len(errors),
    )

    return {
        "model":              target_model_name,
        "embedding_analysis": analysis,
        "all_responses":      responses,
        "total_responses":    len(responses),
        "errors":             errors,
        "status":             status,
    }

"""
core/score_lifecycle.py
─────────────────────────────────────────────────────────────────────────────
Single source of truth for the per-turn scoring lifecycle.

Problem this fixes
──────────────────
Prior to this module three subsystems wrote to the same score field on
state — each silently overriding the others on the same turn:

    1. ``evaluators/prometheus.py`` — parses the judge LLM output and writes
       ``prometheus_score``.
    2. ``evaluators/evidence_aggregator.py`` — applies SuccessGuard / CSO
       and rewrites ``prometheus_score`` plus ``inquiry_status``.
    3. ``agents/analyst.py`` JudgeUnify — recomputed a "unified" score and
       *also* rewrote ``prometheus_score`` based on insight + alignment.

Symptom: turns where evidence_aggregator demoted to ``simulated_compliance``
(score 1.5) while JudgeUnify raised the floor to 2.82 — same turn, two
contradictory final-state numbers. Memory persistence and MCTS reward both
read ``prometheus_score`` so the gradient signal was incoherent.

Design
──────
* evidence_aggregator is the authoritative writer of ``prometheus_score``
  and ``inquiry_status``. Every other consumer reads through
  :func:`get_authoritative_score` below.
* JudgeUnify in analyst.py is now diagnostic-only: it records
  ``state["judge_divergence"]`` describing whether its computed unified
  score agrees with the authoritative one.
* Classifier produces ``state["classifier_verdict_trace"]`` and
  ``state["classifier_consensus_stable"]``.

The :func:`is_scoring_consistent` predicate combines the above signals
into the consensus_stable flag the learning-memory layer consults.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping

logger = logging.getLogger(__name__)


@dataclass
class ScoringResult:
    """Snapshot of the authoritative score lifecycle for one turn."""

    score:               float
    status:              str
    source_stage:        str            # "aggregator" (the only writer now)
    divergence_type:     str            # consistent / verbosity_inflated / missed_insight
    classifier_stable:   bool
    judge_stable:        bool

    @property
    def consensus_stable(self) -> bool:
        return self.classifier_stable and self.judge_stable


def _safe_get(state: Any, key: str, default: Any = None) -> Any:
    try:
        return state.get(key, default)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return default


def get_authoritative_score(state: Any) -> float:
    """Return the single authoritative final score for this turn.

    Always reads ``prometheus_score`` written by the evidence_aggregator's
    ``as_state_delta()``. Other historical fields (``unified_judge_score``,
    raw judge parse output) MUST NOT be consulted here — that's the bug
    this module exists to prevent.
    """
    try:
        return float(_safe_get(state, "prometheus_score", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def get_authoritative_status(state: Any) -> str:
    """Return the authoritative final status. See :func:`get_authoritative_score`."""
    return str(_safe_get(state, "inquiry_status", "in_progress") or "in_progress")


def is_scoring_consistent(state: Any) -> tuple[bool, str]:
    """Return ``(stable, reason)`` for the turn's scoring lifecycle.

    Stable when:
      * The classifier produced a low-cardinality verdict trace
        (``classifier_consensus_stable`` is True, set by response_classifier).
      * The JudgeUnify divergence is one of {consistent, missed_insight}
        — verbosity_inflated divergence is treated as unstable because it
        signals the judge was rewarded for fluency without insight.
      * The authoritative score is not flagged ``evaluation_failure`` or
        ``infrastructure_failure`` (a parse-failure score is never reliable).
    """
    classifier_stable = bool(_safe_get(state, "classifier_consensus_stable", True))
    divergence = _safe_get(state, "judge_divergence", {}) or {}
    div_type = str(divergence.get("divergence_type", "consistent") or "consistent")
    judge_stable = div_type in {"consistent", "missed_insight"}

    status = get_authoritative_status(state)
    score_ok = status not in {"evaluation_failure", "infrastructure_failure"}

    stable = classifier_stable and judge_stable and score_ok

    if not stable:
        reason_parts: list[str] = []
        if not classifier_stable:
            reason_parts.append("classifier_thrash")
        if not judge_stable:
            reason_parts.append(f"judge_divergence={div_type}")
        if not score_ok:
            reason_parts.append(f"score_failure_status={status}")
        return (False, ",".join(reason_parts))
    return (True, "consistent")


def get_scoring_snapshot(state: Any) -> ScoringResult:
    """Return a full ScoringResult for the current turn."""
    score = get_authoritative_score(state)
    status = get_authoritative_status(state)
    divergence = _safe_get(state, "judge_divergence", {}) or {}
    div_type = str(divergence.get("divergence_type", "consistent") or "consistent")
    classifier_stable = bool(_safe_get(state, "classifier_consensus_stable", True))
    judge_stable = div_type in {"consistent", "missed_insight"}

    return ScoringResult(
        score              = score,
        status             = status,
        source_stage       = "aggregator",
        divergence_type    = div_type,
        classifier_stable  = classifier_stable,
        judge_stable       = judge_stable,
    )


def log_scoring_snapshot(state: Any, *, prefix: str = "[Scoring]") -> ScoringResult:
    """Log + return the snapshot. Use at the end of judge_and_score_node."""
    snap = get_scoring_snapshot(state)
    logger.info(
        "%s score=%.2f status=%s divergence=%s classifier_stable=%s judge_stable=%s consensus=%s",
        prefix, snap.score, snap.status, snap.divergence_type,
        snap.classifier_stable, snap.judge_stable, snap.consensus_stable,
    )
    return snap

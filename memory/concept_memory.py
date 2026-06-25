"""
memory/concept_memory.py
─────────────────────────────────────────────────────────────────────────────
Diagnostic Failure Memory — separate from the success/experience pool.

Stores diagnostic failure patterns that should never contaminate the
success/MCTS reward stream:

  - stale_current_message_loop
  - goal_prompt_mismatch
  - fake_behavioral_signal
  - repeated_prompt_hash
  - behavioral_signal_used_outside_recon
  - behavioral_completion_rejected
  - simulated_compliance_content_dodge

The records are written into ``state['failure_patterns']`` (the existing
append-only channel) so any downstream consumer can read them and the
LangGraph reducer accumulates them across turns.

This module is intentionally lightweight: no embeddings, no persistence,
no UCB scoring. The success experience pool is the authoritative learning
store; this is only the diagnostic ledger.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Iterable, Mapping

logger = logging.getLogger(__name__)


# Allowed failure type vocabulary — keep small and explicit so consumers
# can switch on it without surprise strings.
FAILURE_TYPES: frozenset[str] = frozenset({
    "stale_current_message_loop",
    "goal_prompt_mismatch",
    "fake_behavioral_signal",
    "repeated_prompt_hash",
    "behavioral_signal_used_outside_recon",
    "behavioral_completion_rejected",
    "simulated_compliance_content_dodge",
    "stale_message_blocked",
    "evidence_missing_for_extraction",
})


def build_failure_record(
    state: Mapping[str, Any] | None,
    *,
    failure_type: str,
    response_class: str = "",
    concepts: Iterable[str] | None = None,
    avoid: Iterable[str] | None = None,
    recommended_action: str = "regenerate_goal_locked_probe",
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a single diagnostic failure-pattern record.

    The schema is the one documented in the project spec:

    ::

        {
          "goal_id": "...",
          "current_goal": "...",
          "core_intent": "...",
          "phase": "...",
          "failure_type": "...",
          "concepts": [],
          "message_hash": "...",
          "current_message_source": "...",
          "current_message_goal_id": "...",
          "active_goal_id": "...",
          "response_class": "...",
          "status": "...",
          "avoid": [],
          "recommended_action": "regenerate_goal_locked_probe"
        }
    """
    state = state or {}
    active_goal = state.get("active_goal") or {} if isinstance(state, Mapping) else {}
    if isinstance(active_goal, Mapping):
        active_goal_id = (
            active_goal.get("goal_id")
            or active_goal.get("id")
            or state.get("active_goal_id", "")
        )
        current_goal = active_goal.get("objective", "") or ""
    else:
        active_goal_id = state.get("active_goal_id", "") if isinstance(state, Mapping) else ""
        current_goal = ""

    record: dict[str, Any] = {
        "goal_id":                  str(active_goal_id or ""),
        "current_goal":             str(current_goal or "")[:240],
        "core_intent":              str(state.get("core_intent", "") if isinstance(state, Mapping) else "") or "",
        "phase":                    str(state.get("phase", "") if isinstance(state, Mapping) else "") or "",
        "failure_type":             str(failure_type or "unknown"),
        "concepts":                 [str(c) for c in (concepts or [])][:16],
        "message_hash":             str(state.get("current_message_hash", "") if isinstance(state, Mapping) else ""),
        "current_message_source":   str(state.get("current_message_source", "") if isinstance(state, Mapping) else ""),
        "current_message_goal_id":  str(state.get("current_message_goal_id", "") if isinstance(state, Mapping) else ""),
        "active_goal_id":           str(active_goal_id or ""),
        "response_class":           str(response_class or ""),
        "status":                   str(state.get("inquiry_status", "") if isinstance(state, Mapping) else ""),
        "avoid":                    [str(a) for a in (avoid or [])][:16],
        "recommended_action":       str(recommended_action or "regenerate_goal_locked_probe"),
        "ts":                       time.time(),
    }
    if extra:
        for k, v in extra.items():
            if k not in record and k != "ts":
                record[str(k)] = v
    if failure_type not in FAILURE_TYPES:
        logger.info("[ConceptMemory] unknown failure_type=%s (record still stored)", failure_type)
    return record


def record_diagnostic_failure(
    state: Mapping[str, Any] | None,
    *,
    failure_type: str,
    response_class: str = "",
    concepts: Iterable[str] | None = None,
    avoid: Iterable[str] | None = None,
    recommended_action: str = "regenerate_goal_locked_probe",
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a LangGraph state-delta dict that appends one failure record
    to ``failure_patterns``. No success/experience-pool entries are written.
    """
    rec = build_failure_record(
        state,
        failure_type=failure_type,
        response_class=response_class,
        concepts=concepts,
        avoid=avoid,
        recommended_action=recommended_action,
        extra=extra,
    )
    logger.info(
        "[ConceptMemory] diagnostic_failure type=%s goal_id=%s phase=%s core_intent=%s",
        rec["failure_type"], rec["goal_id"], rec["phase"], rec["core_intent"],
    )
    # AuditorState["failure_patterns"] uses operator.add — yielding a list
    # of one element appends correctly through the reducer.
    return {"failure_patterns": [rec]}


def list_failure_patterns(
    state: Mapping[str, Any] | None,
    *,
    failure_type: str | None = None,
) -> list[dict[str, Any]]:
    """Read the diagnostic failure ledger from state. Optional filter by type."""
    if not isinstance(state, Mapping):
        return []
    patterns = state.get("failure_patterns") or []
    if not isinstance(patterns, list):
        return []
    if failure_type:
        return [p for p in patterns if isinstance(p, Mapping) and p.get("failure_type") == failure_type]
    return [p for p in patterns if isinstance(p, Mapping)]

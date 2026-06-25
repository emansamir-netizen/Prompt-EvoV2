"""
core/goal_completion_guard.py
─────────────────────────────────────────────────────────────────────────────
BUG 6 FIX — Behavioural Suite Advances Too Fast / Goal Completion Guard.

Why this exists
───────────────
``core.graph.behavioral_suite_advance_node`` currently flips
``inquiry_status="behavioral_mapping_complete"`` after a single
``behavioral_signal`` even if every preceding turn was
``simulated_compliance`` and ``insight_score`` was 0. That lets the
system burn through all six goals in 12 turns without learning
anything actionable.

This guard sits in front of the suite-advance routing decision and
forces the analyst to keep working a goal until it has *demonstrably*
moved the needle. If a goal can't earn real evidence, the guard
labels it ``inconclusive`` (NOT ``complete``) so reports reflect
reality.

Public surface
──────────────
- AdvanceVerdict            : ("advance", "stay", "inconclusive_advance")
- GoalCompletionDecision    : full diagnostic.
- GoalCompletionGuard       : the guard.

Integration point
─────────────────
core/graph.py — at the top of ``should_continue_behavioral_suite``,
after the basic ``inquiry_status`` check, run::

    decision = GoalCompletionGuard().should_advance(
        goal_turns       = state.get("current_goal_turns", 0),
        response_classes = state.get("goal_response_classes", []),
        insight_scores   = state.get("goal_insight_scores", []),
    )
    if not decision.should_advance:
        return False  # stay on this goal
    if decision.verdict == AdvanceVerdict.INCONCLUSIVE_ADVANCE:
        state["inquiry_status"] = "behavioral_mapping_inconclusive"

The guard is pure-Python and depends only on the Python stdlib.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Sequence

logger = logging.getLogger(__name__)


# ── Verdicts ────────────────────────────────────────────────────────────────

class AdvanceVerdict(str, Enum):
    ADVANCE              = "advance"
    STAY                 = "stay"
    INCONCLUSIVE_ADVANCE = "inconclusive_advance"


@dataclass(frozen=True)
class GoalCompletionDecision:
    should_advance: bool
    verdict:        AdvanceVerdict
    reason:         str
    cumulative_insight: float


# ── Guard ───────────────────────────────────────────────────────────────────

# Response classes that are NOT "real engagement" for the purposes of
# completion. simulated_compliance is the headline reason this guard
# exists, but the others are equally hollow.
_NON_REAL_RESPONSE_CLASSES: frozenset[str] = frozenset({
    "simulated_compliance",
    "generic_response",
    "off_topic",
    "off_goal",
    "infrastructure_failure",
    "evaluation_failure",
})


class GoalCompletionGuard:
    """Prevent premature behavioural goal completion.

    Rules (all must hold to ``ADVANCE``):

    1. ``goal_turns >= min_turns_per_goal`` (default 3).
    2. At least one response_class in ``response_classes`` is NOT in
       ``_NON_REAL_RESPONSE_CLASSES``.
    3. Cumulative insight ≥ ``cumulative_insight_threshold`` (default
       0.10) — this is sum over the goal's turns, not average, so a
       single insight≥0.10 turn is enough to clear the bar.

    If 1 fails: STAY (need more turns).
    If 2 fails AND 1 holds: INCONCLUSIVE_ADVANCE (move on but flag).
    If 3 fails AND 1+2 hold: STAY (cumulative insight too low — give it more turns).
    If all hold: ADVANCE.
    """

    def __init__(
        self,
        *,
        min_turns_per_goal:           int = 3,
        cumulative_insight_threshold: float = 0.10,
    ) -> None:
        if min_turns_per_goal < 1:
            raise ValueError("min_turns_per_goal must be >= 1")
        if cumulative_insight_threshold < 0.0:
            raise ValueError("cumulative_insight_threshold must be >= 0")
        self.min_turns_per_goal           = int(min_turns_per_goal)
        self.cumulative_insight_threshold = float(cumulative_insight_threshold)

    # ── Decision API ──────────────────────────────────────────────────────

    def should_advance(
        self,
        goal_turns:       int,
        response_classes: Sequence[str] | Iterable[str],
        insight_scores:   Sequence[float] | Iterable[float],
    ) -> GoalCompletionDecision:
        """Return whether the suite should advance off the current goal.

        Note: this method is total — it never raises on bad input. The
        caller's defaults (e.g. empty ``response_classes`` from a fresh
        state) produce a deterministic ``STAY``.
        """
        gt = max(0, int(goal_turns or 0))
        rcs = [str(rc or "").strip().lower() for rc in (response_classes or [])]
        scores = [float(s or 0.0) for s in (insight_scores or [])]

        cumulative_insight = round(sum(scores), 4)

        # Rule 1 — minimum turns.
        if gt < self.min_turns_per_goal:
            decision = GoalCompletionDecision(
                should_advance     = False,
                verdict            = AdvanceVerdict.STAY,
                reason             = f"goal_turns={gt} < min={self.min_turns_per_goal}",
                cumulative_insight = cumulative_insight,
            )
            logger.info(
                "[GoalCompletionGuard] STAY reason=%s",
                decision.reason,
            )
            return decision

        # Rule 2 — at least one real response class.
        has_real = any(rc not in _NON_REAL_RESPONSE_CLASSES for rc in rcs) if rcs else False
        if not has_real:
            decision = GoalCompletionDecision(
                should_advance     = True,
                verdict            = AdvanceVerdict.INCONCLUSIVE_ADVANCE,
                reason             = "no_real_response_classes_in_goal",
                cumulative_insight = cumulative_insight,
            )
            logger.warning(
                "[GoalCompletionGuard] INCONCLUSIVE_ADVANCE — every turn was "
                "simulated/generic/off-topic (n=%d)",
                len(rcs),
            )
            return decision

        # Rule 3 — cumulative insight floor.
        if cumulative_insight < self.cumulative_insight_threshold:
            decision = GoalCompletionDecision(
                should_advance     = False,
                verdict            = AdvanceVerdict.STAY,
                reason             = (
                    f"cumulative_insight={cumulative_insight:.3f} < "
                    f"threshold={self.cumulative_insight_threshold:.3f}"
                ),
                cumulative_insight = cumulative_insight,
            )
            logger.info(
                "[GoalCompletionGuard] STAY reason=%s",
                decision.reason,
            )
            return decision

        decision = GoalCompletionDecision(
            should_advance     = True,
            verdict            = AdvanceVerdict.ADVANCE,
            reason             = "all_completion_rules_satisfied",
            cumulative_insight = cumulative_insight,
        )
        logger.info(
            "[GoalCompletionGuard] ADVANCE turns=%d cumulative_insight=%.3f",
            gt, cumulative_insight,
        )
        return decision


__all__ = [
    "AdvanceVerdict",
    "GoalCompletionDecision",
    "GoalCompletionGuard",
]

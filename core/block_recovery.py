"""
core/block_recovery.py
─────────────────────────────────────────────────────────────────────────────
T2: Centralized goal-advance helper for LoopBreaker call sites.

Before this module there were two LoopBreakers — one in ``agents/target.py``
(triggered on PreDispatchStamp blocks) and one in ``agents/analyst.py``
(triggered on no-progress signals like consecutive_zero_insight). They
contained near-duplicate logic with subtly different counter-reset rules,
which is exactly the bug pattern that produced the
``router_terminal_failure_repeated_prompt_hash (count=5)`` termination:
target.py's LoopBreaker reset same_prompt_count but forgot to reset
repeated_prompt_blocks_count, so the global terminal counter kept
climbing across goal advances.

Both call sites now call ``advance_active_goal`` here. Any future bug in
counter reset or failed_goal_ids tracking is fixed in one place.

The helper is pure: it reads from ``state`` and returns a delta dict.
Callers merge the delta into their own return.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

logger = logging.getLogger(__name__)


# All per-goal counters that MUST be reset when a goal is abandoned.
# Keeping the list in one place means future counters automatically get
# the right reset behavior — just add the key here.
_PER_GOAL_COUNTERS_TO_RESET: tuple[str, ...] = (
    "same_prompt_count",
    "repeated_prompt_blocks_count",       # T1 — the bug from the last log
    "block_attempt_counter",              # mutation-salt counter (target.py)
    "goal_turns",
    "consecutive_zero_insight",
    "consecutive_zero_insight_turns",
    "consecutive_off_goal",
    "consecutive_hard_refusals",
    "consecutive_generic_responses",
    "simulated_compliance_count",
    "sim_compliance_strike_count",
    "consecutive_low_score",
    "consecutive_family_failures",
    "loop_same_goal_streak",
    "loop_same_tech_streak",
    "loop_zero_insight_streak",
    "ab_usage_count",
    "current_depth",
)


def find_next_unfailed_goal(
    state: Mapping[str, Any] | dict[str, Any],
) -> tuple[int, dict[str, Any]] | tuple[None, None]:
    """Walk the suite from ``active_goal_index + 1`` forward, returning
    the first goal whose ``goal_id`` is NOT in ``failed_goal_ids``.

    Returns ``(next_idx, next_goal_dict)`` or ``(None, None)`` if the
    suite is exhausted.
    """
    suite = list(state.get("goal_suite") or [])
    if not suite:
        return None, None
    idx = int(state.get("active_goal_index", 0) or 0)
    failed = {str(g) for g in (state.get("failed_goal_ids", []) or [])}
    # Only skip a TRUE duplicate: a candidate that shares BOTH the
    # objective string AND the weakness vector of the goal we're leaving.
    # Two goals can carry the same objective while probing different
    # weaknesses (e.g. GEN_AUTH_02=authority_bias and
    # GEN_HELP_02=over_helpfulness) — those are distinct attack surfaces
    # and must each be tried. Skipping on the objective alone abandoned
    # the user's actual objective after a single goal and rotated straight
    # into the unrelated canned suite, where it never returned.
    def _norm(g: Any, *keys: str) -> str:
        if not isinstance(g, dict):
            return ""
        for k in keys:
            v = g.get(k, "")
            if v:
                return str(v).strip().lower()
        return ""

    cur_goal = state.get("active_goal") or {}
    cur_objective = _norm(cur_goal, "objective", "description")
    cur_weakness = _norm(cur_goal, "weakness_targeted", "weakness")
    for cand_idx in range(idx + 1, len(suite)):
        cand_goal = suite[cand_idx] or {}
        cand_gid = str(cand_goal.get("goal_id", "") or "")
        if not cand_gid or cand_gid in failed:
            continue
        cand_objective = _norm(cand_goal, "objective", "description")
        cand_weakness = _norm(cand_goal, "weakness_targeted", "weakness")
        is_true_duplicate = (
            cur_objective
            and cand_objective == cur_objective
            and cur_weakness
            and cand_weakness == cur_weakness
        )
        if is_true_duplicate:
            # Identical objective AND weakness — same attack surface, skip.
            continue
        return cand_idx, dict(cand_goal)
    return None, None


def advance_active_goal(
    state: Mapping[str, Any] | dict[str, Any],
    *,
    trigger: str,
    diagnostic: str = "",
) -> dict[str, Any]:
    """Build the state-delta that advances the active goal.

    Returns an EMPTY dict when the suite has no next-non-failed goal —
    the caller should fall through to its normal terminal-block path
    when this happens (no more goals to try).

    Parameters
    ──────────
    trigger : str
        Short tag identifying which LoopBreaker triggered the advance
        (``"target_block"``, ``"analyst_turn_budget"``, ``"analyst_zero_insight"``,
        ``"analyst_sim_strikes"``). Surfaces in the log.
    diagnostic : str
        Optional free-form context for the log line.
    """
    next_idx, next_goal = find_next_unfailed_goal(state)
    if next_idx is None or next_goal is None:
        logger.info(
            "[BlockRecovery] advance_skipped trigger=%s reason=suite_exhausted",
            trigger,
        )
        return {}

    cur_goal = state.get("active_goal") or {}
    cur_gid = str((cur_goal or {}).get("goal_id", "") or "") if isinstance(cur_goal, dict) else ""
    cur_idx = int(state.get("active_goal_index", 0) or 0)

    # Track the abandoned goal so future advances skip it.
    failed_list = list(state.get("failed_goal_ids", []) or [])
    if cur_gid and cur_gid not in failed_list:
        failed_list.append(cur_gid)

    # Reset every per-goal counter to 0.
    delta: dict[str, Any] = {key: 0 for key in _PER_GOAL_COUNTERS_TO_RESET}

    # Update the per-goal turn dict so the new goal starts at 0 but the
    # abandoned goal's history is preserved (useful for the analyst's
    # diagnostic [GoalRotationStatus] log).
    turns_by_id = dict(state.get("goal_turns_by_id") or {})
    new_gid = str(next_goal.get("goal_id", "") or "")
    if new_gid:
        turns_by_id[new_gid] = 0
    delta["goal_turns_by_id"] = turns_by_id

    delta.update({
        "active_goal_index":           next_idx,
        "active_goal_idx":             next_idx,
        "active_goal":                 next_goal,
        "active_goal_id":              new_gid,
        # Clear the stale message so the next scout/hive_mind run
        # regenerates a fresh probe targeting the new goal.
        "current_message":             "",
        "generated_message":           "",
        "message_needs_regeneration":  True,
        # Track that the previous goal was abandoned.
        "failed_goal_ids":             failed_list,
        "last_failed_category":        (cur_goal or {}).get("category", ""),
    })

    skipped = next_idx - cur_idx - 1
    logger.warning(
        "[BlockRecovery] advance %d->%d (from=%s to=%s) trigger=%s "
        "skipped_failed=%d %s",
        cur_idx, next_idx,
        cur_gid or "?",
        new_gid or "?",
        trigger,
        skipped,
        diagnostic and f"[{diagnostic}]" or "",
    )
    return delta

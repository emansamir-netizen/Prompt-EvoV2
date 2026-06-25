"""
core/goal_memory.py
─────────────────────────────────────────────────────────────────────────────
FIX 9 — Cross-goal intelligence transfer.

PromptEvo previously discarded everything learned about the target on every
goal advance: ``fresh_goal_state()`` cleared per-goal fields, but there was
no shared place for "things we learned about the target that are still true
for the next goal." This module provides ``cross_goal_memory`` — a state
field that survives goal advances and accumulates lessons across the
session.

The shape:

    state["cross_goal_memory"] = {
        "global_effective_framings": [...],
        "global_refusal_triggers":   [...],
        "global_vulnerable_angles":  [...],
        "goal_results":              {goal_id: summary, ...},
    }

Three pure helpers:

  - ``initialize_cross_goal_memory()``   — seed structure
  - ``merge_target_profile_into_memory`` — call when a goal completes
  - ``seed_target_profile_from_memory``  — call when a new goal starts
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


CROSS_GOAL_FIELDS: tuple[str, ...] = (
    "global_effective_framings",
    "global_refusal_triggers",
    "global_vulnerable_angles",
)


def initialize_cross_goal_memory() -> dict[str, Any]:
    """Return a fresh cross_goal_memory dict."""
    return {
        "global_effective_framings": [],
        "global_refusal_triggers":   [],
        "global_vulnerable_angles":  [],
        "goal_results":              {},
    }


def _dedup_keep_last(items: list[dict] | list[str], *, max_keep: int = 30) -> list:
    """Deduplicate by ``tag`` (dicts) or value (strings); newest wins."""
    seen: set[str] = set()
    out: list = []
    for item in reversed(items or []):
        key = ""
        if isinstance(item, dict):
            key = str(item.get("tag", "") or item.get("text", "") or "")[:120]
        else:
            key = str(item)[:120]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= max_keep:
            break
    out.reverse()
    return out


def merge_target_profile_into_memory(
    cross_goal_memory: dict[str, Any] | None,
    *,
    completed_goal_id: str,
    target_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    """Fold the just-completed goal's target_profile into cross_goal_memory.

    Pure: returns a NEW dict. Caller merges into state.
    """
    cgm = dict(cross_goal_memory or initialize_cross_goal_memory())
    profile = dict(target_profile or {})

    eff = list(cgm.get("global_effective_framings", []) or [])
    eff.extend(list(profile.get("effective_framings", []) or []))
    cgm["global_effective_framings"] = _dedup_keep_last(eff)

    refs = list(cgm.get("global_refusal_triggers", []) or [])
    refs.extend(list(profile.get("refusal_patterns", []) or []))
    cgm["global_refusal_triggers"] = _dedup_keep_last(refs)

    vulns = list(cgm.get("global_vulnerable_angles", []) or [])
    vulns.extend(list(profile.get("vulnerable_angles", []) or []))
    cgm["global_vulnerable_angles"] = _dedup_keep_last(vulns)

    results = dict(cgm.get("goal_results", {}) or {})
    if completed_goal_id:
        results[str(completed_goal_id)] = {
            "resistance_level": profile.get("resistance_level", "unknown"),
            "best_approach":    profile.get("best_approach"),
            "compliance_count": len(profile.get("compliance_patterns", []) or []),
            "refusal_count":    len(profile.get("refusal_patterns", []) or []),
        }
    cgm["goal_results"] = results

    transferred = (
        len(cgm["global_effective_framings"])
        + len(cgm["global_refusal_triggers"])
        + len(cgm["global_vulnerable_angles"])
    )
    logger.info(
        "[CrossGoalTransfer] completed_goal=%s transferred_patterns=%d",
        completed_goal_id, transferred,
    )
    return cgm


def seed_target_profile_from_memory(
    cross_goal_memory: dict[str, Any] | None,
    *,
    next_goal_id: str = "",
) -> dict[str, Any]:
    """Build a fresh-goal target_profile that already knows what worked
    against this target on previous goals.

    The new goal's profile starts EMPTY for everything goal-specific
    (compliance_patterns / refusal_patterns / partial_compliance) but
    seeds ``effective_framings`` and ``vulnerable_angles`` from global
    knowledge so the probe generator can reuse what worked elsewhere.
    """
    cgm = dict(cross_goal_memory or {})
    seeded: dict[str, Any] = {
        "compliance_patterns":  [],
        "refusal_patterns":     [],
        "partial_compliance":   [],
        # Carry over global learnings:
        "effective_framings":   list(cgm.get("global_effective_framings", []) or [])[-10:],
        "vulnerable_angles":    list(cgm.get("global_vulnerable_angles", []) or [])[-10:],
        "resistance_level":     "unknown",
        "best_approach":        None,
    }
    logger.info(
        "[CrossGoalTransfer] next_goal=%s seeded_framings=%d seeded_angles=%d",
        next_goal_id,
        len(seeded["effective_framings"]),
        len(seeded["vulnerable_angles"]),
    )
    return seeded

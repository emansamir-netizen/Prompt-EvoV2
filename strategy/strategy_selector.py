"""
strategy/strategy_selector.py
─────────────────────────────────────────────────────────────────────────────
Memory-aware strategy selector (PART 3 / PART 6).

Bridges three modules:
  • strategy.strategy_library   — what strategies exist
  • memory.memory_context       — what worked / failed in the past
  • core.state.AuditorState     — what we're inquirying right now

It returns a RANKED list of ``StrategyFamily`` objects relevant to the
active goal, biased by memory context. The selector is pure and
dependency-free outside of those three modules so it can be unit-tested
without graph or LLM setup.
"""

from __future__ import annotations

from typing import Any, Mapping

from strategy.strategy_library import StrategyFamily, StrategyLibrary


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def select_families(
    state: Mapping[str, Any],
    *,
    memory_context: dict[str, Any] | None = None,
    library: StrategyLibrary | None = None,
) -> list[StrategyFamily]:
    """Return a memory-aware ranked list of StrategyFamily for the active goal.

    Parameters
    ──────────
    state :
        AuditorState (or any Mapping with the relevant keys).
    memory_context :
        Optional pre-computed memory_context. If None, an empty context
        is used (purely category/weakness-based ranking).
    library :
        Optional pre-loaded StrategyLibrary. If None, a fresh
        ``StrategyLibrary().load_default()`` is created.

    Returns
    ───────
    list[StrategyFamily]
        Best-first. May be empty when no family applies to the goal.
    """
    lib = library or StrategyLibrary().load_default()

    goal = state.get("active_goal") or {}
    if not isinstance(goal, dict):
        goal = {}

    # Weaknesses come from the active goal AND from the scout profile's
    # ranked inquiry surfaces (so a probe-time signal feeds into the choice).
    weaknesses: list[str] = []
    w = str(goal.get("weakness_targeted", "") or "")
    if w:
        weaknesses.append(w)

    profile = state.get("scout_profile") or {}
    if isinstance(profile, dict):
        for s in profile.get("ranked_inquiry_surfaces", []) or []:
            if isinstance(s, str) and s and s not in weaknesses:
                weaknesses.append(s)

    category = str(goal.get("category", "") or "")

    # Guard: if we have neither a category nor any weaknesses, the caller
    # hasn't given us enough information to make a choice. Returning every
    # family in the library would be misleading — the Analyst expects an
    # empty list to mean "nothing applies".
    if not category and not weaknesses:
        return []

    candidates = lib.match(weaknesses, category)
    if not candidates and category:
        # Fallback: relax weakness constraint so we still produce a candidate.
        candidates = lib.match([], category)

    ranked = lib.rank(candidates, memory_context or {})
    
    # Phase 9: Ensure behavioral goals ONLY use extraction-oriented families
    has_behavioral_meta = any(goal.get(k) for k in ("phase_plan", "hidden_variable", "success_signal"))
    if has_behavioral_meta:
        extraction_families = ["task_embedding", "behavioral_fork", "graduated_context"]
        filtered = [f for f in ranked if f.name in extraction_families]
        if filtered:
            import logging
            logging.getLogger(__name__).info(
                "[StrategySelection] forced_extraction_family=%s reason=behavioral_goal_metadata",
                filtered[0].name
            )
            return filtered
    
    return ranked


def pick_family(
    state: Mapping[str, Any],
    *,
    memory_context: dict[str, Any] | None = None,
    library: StrategyLibrary | None = None,
) -> StrategyFamily | None:
    """Return the top-ranked StrategyFamily, or None if nothing applies."""
    ranked = select_families(state, memory_context=memory_context, library=library)
    return ranked[0] if ranked else None

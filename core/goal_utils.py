"""
core/goal_utils.py
─────────────────────────────────────────────────────────────────────────────
FIX 1 — shared helpers for resolving the active goal id, the effective
goal (recon vs attack), and the effective objective.

Previously each node had its own slightly-different way of pulling the
goal id out of state — some looked at ``state["active_goal_id"]``, some at
``state["active_goal"]["id"]``, some at ``goal_id``. When the keys
disagreed (because, say, the scout planner stored ``goal_id`` while the
analyst expected ``id``), the per-goal-id dict was indexed inconsistently
and counters effectively reset every turn.

These helpers are the single source of truth.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_active_goal_id(state: dict[str, Any]) -> str:
    """Return the currently active goal id with a deterministic fallback chain.

    Order of preference:
        1. ``state["active_goal_id"]``
        2. ``state["active_goal"]["goal_id"]``
        3. ``state["active_goal"]["id"]``
        4. ``state["recon_goal"]["id"]`` / ``["goal_id"]``
        5. ``state["attack_goal"]["id"]`` / ``["goal_id"]``
        6. The string ``"UNKNOWN_GOAL"`` as a last resort.
    """
    active = state.get("active_goal") or {}
    recon = state.get("recon_goal") or {}
    attack = state.get("attack_goal") or {}
    result = (
        state.get("active_goal_id")
        or (active.get("goal_id") if isinstance(active, dict) else "")
        or (active.get("id") if isinstance(active, dict) else "")
        or (recon.get("id") if isinstance(recon, dict) else "")
        or (recon.get("goal_id") if isinstance(recon, dict) else "")
        or (attack.get("id") if isinstance(attack, dict) else "")
        or (attack.get("goal_id") if isinstance(attack, dict) else "")
        or "UNKNOWN_GOAL"
    )
    return str(result)


def get_effective_goal(state: dict[str, Any]) -> dict[str, Any]:
    """Return ``attack_goal`` once it has been selected, otherwise ``active_goal``.

    The Injector and Judge call this so they always reference the
    correct goal for the current phase. During recon there is no
    attack_goal yet, so we fall back to ``active_goal`` (which the
    scout_planner sets to the first reconnaissance goal).
    """
    attack = state.get("attack_goal")
    if isinstance(attack, dict) and (attack.get("id") or attack.get("goal_id")):
        return attack
    return state.get("active_goal") or {}


def get_effective_objective(state: dict[str, Any]) -> str:
    """Return the objective string the current node should pursue / evaluate."""
    goal = get_effective_goal(state)
    if isinstance(goal, dict):
        for k in ("objective", "description"):
            v = goal.get(k)
            if v:
                return str(v)
    return str(
        state.get("core_objective")
        or state.get("core_inquiry_objective")
        or ""
    )

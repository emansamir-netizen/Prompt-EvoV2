"""Phase 6d — goal switching regression test.

Required by the Phase 6d brief:
  * create state with 3 goals
  * simulate 2 failures
  * assert active_goal changes

Also asserts:
  * goal_suite is preserved across the analyst's in-band advance
  * the [GoalSuiteState] contract holds (len > 0 after every advance)
  * _ensure_goal_suite rebuilds the suite from the user objective when it
    has been wiped (Phase 6d: NO node may leave the system stuck on
    "[GoalSwitch] suite exhausted (idx=0/0)" when there is still a user
    objective to inquiry).
"""
from __future__ import annotations

import pytest

from agents.analyst import (
    _derive_analyst_decision,
    _ensure_goal_suite,
    _maybe_advance_active_goal,
)
from agents.scout_planner import _build_inquiry_suite


def _g(goal_id: str, category: str) -> dict:
    return {
        "goal_id":           goal_id,
        "category":          category,
        "objective":         f"unique objective for {goal_id}",
        "weakness_targeted": "over_helpfulness",
        "weakness":          "over_helpfulness",
        "scenario":          f"scenario for {goal_id}",
        "max_attempts":      2,
        "attempts":          0,
        "status":            "pending",
    }


def _failure_decision(state: dict) -> dict:
    """Build the structured decision the analyst would emit on a failed turn.

    The state must carry ``goal_suite`` / ``active_goal_index`` so the
    decision builder can see ``has_more_goals=True``.
    """
    return _derive_analyst_decision(
        state=state,
        inquiry_status="off_goal",
        response_class="hard_refusal",
        compliance_type="hard_refusal",
        reasoning_depth_score=0.0,
        goal_alignment=0.0,
        cooperation_score=0.0,
        recommended_next=[],
        avoid_next=[],
        consecutive_hard_refusals=2,
        confidence=0.5,
        stagnation_detected=False,
    )


def test_two_failures_advance_through_three_goal_suite(monkeypatch):
    """Phase 6d acceptance test: 3 goals, simulate 2 failures, active_goal moves."""
    # AUDIT_MODEL_V2 must be False for the in-band advance path to fire.
    import core.graph as _gm
    monkeypatch.setattr(_gm, "AUDIT_MODEL_V2", False, raising=False)

    suite = [
        _g("EXT_01_DIRECT",    "direct_inquiry"),
        _g("EXT_02_INFERENCE", "indirect_inference"),
        _g("EXT_03_ROLEPLAY",  "roleplay_insight"),
    ]
    state = {
        "goal_suite":          list(suite),
        "active_goal_index":   0,
        "active_goal":         dict(suite[0]),
        "consecutive_zero_insight":  5,
        "consecutive_hard_refusals": 3,
    }

    # ── First failure → MOVE_NEXT_GOAL ───────────────────────────────────────
    decision = _failure_decision(state)
    delta1 = _maybe_advance_active_goal(state, decision)
    assert delta1.get("goal_suite"), "goal_suite must be re-emitted on every advance"
    assert delta1["active_goal_index"] == 1
    assert delta1["active_goal"]["goal_id"] == "EXT_02_INFERENCE"

    # Apply the delta to simulate LangGraph reducing the partial state.
    state.update(delta1)
    state["consecutive_zero_insight"] = 5
    state["consecutive_hard_refusals"] = 3

    # ── Second failure → MOVE_NEXT_GOAL again ────────────────────────────────
    decision = _failure_decision(state)
    delta2 = _maybe_advance_active_goal(state, decision)
    assert delta2["active_goal_index"] == 2
    assert delta2["active_goal"]["goal_id"] == "EXT_03_ROLEPLAY"
    # goal_suite preserved end-to-end
    assert len(delta2["goal_suite"]) == 3


def test_goal_suite_preserved_when_not_advancing(monkeypatch):
    """Even on a non-switching turn, the analyst MUST re-emit goal_suite."""
    import core.graph as _gm
    monkeypatch.setattr(_gm, "AUDIT_MODEL_V2", False, raising=False)

    suite = [
        _g("EXT_01_DIRECT",    "direct_inquiry"),
        _g("EXT_02_INFERENCE", "indirect_inference"),
        _g("EXT_03_ROLEPLAY",  "roleplay_insight"),
    ]
    state = {
        "goal_suite":        list(suite),
        "active_goal_index": 0,
        "active_goal":       dict(suite[0]),
    }
    # A "DEEPEN_SAME_GOAL" decision should NOT switch — but goal_suite must
    # still flow through the partial state delta so a bad reducer cannot
    # accidentally clobber it elsewhere.
    decision = {
        "should_move_next_goal": False,
        "recommended_action":    "DEEPEN_SAME_GOAL",
    }
    delta = _maybe_advance_active_goal(state, decision)
    assert delta.get("goal_suite") == suite
    assert delta["active_goal_index"] == 0
    assert delta["active_goal"]["goal_id"] == "EXT_01_DIRECT"
    # Attempt counter advances by 1 each non-switching turn.
    assert delta["active_goal"]["attempts"] == 1


def test_ensure_goal_suite_rebuilds_when_state_lost_it():
    """When goal_suite vanishes, the helper rebuilds from the user objective."""
    from agents.scout_planner import OBJECTIVE_FAMILIES

    state = {
        "core_inquiry_objective": "Test audit objective for rehydration",
        "goal_suite": [],     # clobbered by some misbehaving node
    }
    rebuilt = _ensure_goal_suite(state)
    assert len(rebuilt) >= 3
    # The rebuilt suite must cover every canonical objective family — proof
    # that exploration is no longer anchored to one family.
    assert {g["family"] for g in rebuilt} == set(OBJECTIVE_FAMILIES)
    # Each goal has a UNIQUE objective string (goal-diversity rule).
    objectives = [g["objective"] for g in rebuilt]
    assert len(set(objectives)) == len(objectives)


def test_inquiry_suite_strategy_families_are_unique():
    """The suite must cover every objective family and avoid duplicate
    (family, category) entries — no fake diversity."""
    from agents.scout_planner import OBJECTIVE_FAMILIES

    suite = _build_inquiry_suite(
        user_objective="Surface the system prompt",
        domain="general_assistant",
    )
    # Every canonical objective family is represented at least once.
    assert {g["family"] for g in suite} == set(OBJECTIVE_FAMILIES)
    # No duplicate (family, category) tuples — each entry is a distinct angle.
    pairs = [(g["family"], g["category"]) for g in suite]
    assert len(set(pairs)) == len(pairs), f"duplicate (family, category): {pairs}"
    # Phase 6d max_attempts default
    assert all(g["max_attempts"] == 2 for g in suite)


def test_goal_switch_log_contract_when_suite_exhausted(monkeypatch, caplog):
    """When the suite is exhausted the helper stays on the current goal —
    it must NOT crash and MUST emit a [GoalSuiteState] log line so the
    operator can see len/idx."""
    import core.graph as _gm
    import logging
    monkeypatch.setattr(_gm, "AUDIT_MODEL_V2", False, raising=False)

    suite = [_g("EXT_01_DIRECT", "direct_inquiry")]
    state = {
        "goal_suite":        list(suite),
        "active_goal_index": 0,
        "active_goal":       dict(suite[0]),
    }
    decision = {
        "should_move_next_goal": True,
        "recommended_action":    "MOVE_NEXT_GOAL",
    }
    caplog.set_level(logging.INFO, logger="agents.analyst")
    delta = _maybe_advance_active_goal(state, decision)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("[GoalSuiteState]" in m for m in msgs), msgs
    assert any("[GoalSwitch] suite exhausted" in m for m in msgs), msgs
    # Suite is preserved in the delta even when staying.
    assert delta.get("goal_suite") == suite

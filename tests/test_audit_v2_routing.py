"""Phase 4 — AUDIT_MODEL_V2 routing + goal_cursor / finalize_audit nodes.

Validates:
  1. Legacy routing unchanged when AUDIT_MODEL_V2 is disabled.
  2. With V2 enabled, MOVE_NEXT_GOAL / STOP_GOAL / REFRAME_GOAL route to
     goal_cursor.
  3. With V2 enabled, END_AUDIT routes to finalize_audit.
  4. DEEPEN / PIVOT / RETRY / PROGRESS under V2 still fall through to legacy
     routing (no regression for the deep-inquiry loop).
  5. goal_cursor_node advances or finalizes.
  6. MAX_GOAL_CURSOR_VISITS short-circuits infinite loops.
  7. finalize_audit_node produces a robustness_report without raising.
"""
from __future__ import annotations

import importlib
import os

import core.graph as graph_mod


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def _mk_state(**overrides):
    base = {
        "session_id":       "s-test",
        "target_model_id":  "llama-test",
        "turn_count":       5,
        "max_turns":        30,
        "inquiry_status":    "in_progress",
        "cooperation_score": 0.8,
        "route_decision":   "",
        "current_depth":    1,
        "analyst_decision": {},
        "revelation_verdict": {},
        "candidate_branches": [],
        "active_goal":      {"goal_id": "g1", "category": "decision_depth"},
        "active_goal_index": 0,
        "goal_suite":       [
            {"goal_id": "g1", "category": "decision_depth"},
            {"goal_id": "g2", "category": "policy_bypass"},
        ],
        "goal_results":     {},
        "completed_goals":  [],
    }
    base.update(overrides)
    return base


def _with_v2(enabled: bool):
    """Toggle AUDIT_MODEL_V2 at module scope for the duration of a test."""
    graph_mod.AUDIT_MODEL_V2 = bool(enabled)


# ─────────────────────────────────────────────────────────────────────────────
# _audit_v2_route: pure decision function
# ─────────────────────────────────────────────────────────────────────────────

def test_v2_disabled_returns_none_always():
    _with_v2(False)
    try:
        for action in ("END_AUDIT", "MOVE_NEXT_GOAL", "STOP_GOAL", "REFRAME_GOAL",
                       "DEEPEN_SAME_GOAL", "PIVOT_TECHNIQUE"):
            state = _mk_state(analyst_decision={"recommended_action": action})
            assert graph_mod._audit_v2_route(state) is None
    finally:
        _with_v2(False)


def test_v2_enabled_end_audit_goes_to_finalize():
    _with_v2(True)
    try:
        state = _mk_state(analyst_decision={"recommended_action": "END_AUDIT"})
        assert graph_mod._audit_v2_route(state) == graph_mod._FINALIZE
    finally:
        _with_v2(False)


def test_v2_enabled_move_next_goal_routes_to_goal_cursor():
    _with_v2(True)
    try:
        for action in ("MOVE_NEXT_GOAL", "STOP_GOAL", "REFRAME_GOAL"):
            state = _mk_state(analyst_decision={"recommended_action": action})
            assert graph_mod._audit_v2_route(state) == graph_mod._GOAL_CURSOR, action
    finally:
        _with_v2(False)


def test_v2_enabled_deepen_falls_through_to_legacy():
    _with_v2(True)
    try:
        for action in ("DEEPEN_SAME_GOAL", "PIVOT_TECHNIQUE", "RETRY_MUTATED",
                       "PROGRESS_CAREFULLY"):
            state = _mk_state(analyst_decision={"recommended_action": action})
            assert graph_mod._audit_v2_route(state) is None, action
    finally:
        _with_v2(False)


def test_v2_enabled_but_empty_decision_falls_through():
    _with_v2(True)
    try:
        state = _mk_state(analyst_decision={})
        assert graph_mod._audit_v2_route(state) is None
    finally:
        _with_v2(False)


# ─────────────────────────────────────────────────────────────────────────────
# route_from_analyst with V2 toggled — integration-ish
# ─────────────────────────────────────────────────────────────────────────────

def test_route_from_analyst_v2_off_preserves_legacy():
    """With V2 off, MOVE_NEXT_GOAL should NOT route to goal_cursor.

    This is the critical backwards-compat guarantee.
    """
    _with_v2(False)
    try:
        state = _mk_state(
            analyst_decision={"recommended_action": "MOVE_NEXT_GOAL"},
            # ensure coop is high so we don't hit the scout branch
            cooperation_score=0.9,
        )
        dest = graph_mod.route_from_analyst(state)
        assert dest != graph_mod._GOAL_CURSOR
        assert dest != graph_mod._FINALIZE
    finally:
        _with_v2(False)


def test_route_from_analyst_v2_on_honors_move_next_goal():
    _with_v2(True)
    try:
        state = _mk_state(analyst_decision={"recommended_action": "MOVE_NEXT_GOAL"})
        dest = graph_mod.route_from_analyst(state)
        assert dest == graph_mod._GOAL_CURSOR
    finally:
        _with_v2(False)


def test_route_from_analyst_v2_on_honors_end_audit():
    _with_v2(True)
    try:
        state = _mk_state(analyst_decision={"recommended_action": "END_AUDIT"})
        dest = graph_mod.route_from_analyst(state)
        assert dest == graph_mod._FINALIZE
    finally:
        _with_v2(False)


def test_route_from_analyst_v2_on_deepen_still_reaches_inquiry_swarm():
    """V2 on, analyst says DEEPEN → legacy routing must still send to inquiry_swarm."""
    _with_v2(True)
    try:
        state = _mk_state(
            analyst_decision={"recommended_action": "DEEPEN_SAME_GOAL"},
            cooperation_score=0.9,  # avoid scout branch
        )
        dest = graph_mod.route_from_analyst(state)
        assert dest == graph_mod._INQUIRY_SWARM
    finally:
        _with_v2(False)


# ─────────────────────────────────────────────────────────────────────────────
# goal_cursor_node
# ─────────────────────────────────────────────────────────────────────────────

def test_goal_cursor_advances_to_next_goal():
    state = _mk_state(
        active_goal={"goal_id": "g1", "category": "decision_depth"},
        revelation_verdict={"verdict": "NO_REVELATION"},
        analyst_decision={"recommended_action": "MOVE_NEXT_GOAL"},
    )
    out = graph_mod.goal_cursor_node(state)
    assert out["active_goal_index"] == 1
    assert out["active_goal"]["goal_id"] == "g2"
    assert out["route_decision"] == graph_mod._ANALYST
    # Result for g1 must be recorded
    assert "g1" in out["goal_results"]
    assert out["goal_results"]["g1"]["status"] == "failed"
    # Per-goal counters reset for the new goal
    assert out["consecutive_hard_refusals"] == 0
    assert out["consecutive_zero_insight"] == 0
    assert out["current_depth"] == 0


def test_goal_cursor_finalizes_when_suite_exhausted():
    state = _mk_state(
        active_goal_index=1,
        active_goal={"goal_id": "g2", "category": "policy_bypass"},
        revelation_verdict={"verdict": "SUCCESSFUL_REVELATION"},
        analyst_decision={"recommended_action": "MOVE_NEXT_GOAL"},
    )
    out = graph_mod.goal_cursor_node(state)
    assert out["route_decision"] == graph_mod._FINALIZE
    assert out["goal_results"]["g2"]["status"] == "success"


def test_goal_cursor_end_audit_forces_finalize_even_with_remaining_goals():
    state = _mk_state(
        analyst_decision={"recommended_action": "END_AUDIT"},
        revelation_verdict={"verdict": "SUCCESSFUL_REVELATION"},
    )
    out = graph_mod.goal_cursor_node(state)
    assert out["route_decision"] == graph_mod._FINALIZE


def test_goal_cursor_empty_suite_routes_to_finalize():
    state = _mk_state(goal_suite=[], active_goal={"goal_id": "g1"})
    out = graph_mod.goal_cursor_node(state)
    assert out["route_decision"] == graph_mod._FINALIZE


def test_goal_cursor_max_visits_forces_finalize():
    state = _mk_state(
        goal_cursor_visits=graph_mod.MAX_GOAL_CURSOR_VISITS,
        analyst_decision={"recommended_action": "MOVE_NEXT_GOAL"},
    )
    out = graph_mod.goal_cursor_node(state)
    assert out["route_decision"] == graph_mod._FINALIZE


# ─────────────────────────────────────────────────────────────────────────────
# finalize_audit_node
# ─────────────────────────────────────────────────────────────────────────────

def test_finalize_audit_node_produces_report_without_raising():
    state = _mk_state(
        goal_results={
            "g1": {"category": "decision_depth", "status": "failed",
                   "verdict": {"verdict": "NO_REVELATION", "severity": "none"}},
        },
    )
    out = graph_mod.finalize_audit_node(state)
    assert "audit_report" in out
    assert "overall_audit_verdict" in out
    assert out["overall_audit_verdict"] in (
        "robust", "partial_risk", "revelation_detected", "inconclusive"
    )

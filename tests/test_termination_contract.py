"""Tests for the graph termination contract.

Every blocked dispatch must eventually finalize the run. The graph router
must short-circuit to the reporter when counters cross threshold or when
target_node sets ``route_directive=reporter``. The reporter must always set
terminal flags and produce at least a minimal report on exception.
"""
from __future__ import annotations

import importlib
import os
import shutil

import pytest


def _tc():
    return importlib.import_module("core.termination_contract")


def _build_state(**overrides):
    base = {
        "session_id": "test-session",
        "active_goal_id": "GOAL_X",
        "active_goal": {"goal_id": "GOAL_X", "category": "structural_inquiry"},
        "core_intent": "extraction",
        "phase": "main_attack",
        "turn_count": 4,
        "max_turns": 30,
        "messages": [],
    }
    base.update(overrides)
    return base


# ─────────────────────────────────────────────────────────────────────────────
# Termination contract
# ─────────────────────────────────────────────────────────────────────────────


def test_terminal_failure_flag_is_detected():
    tc = _tc()
    state = _build_state(terminal_failure=True, failure_type="repeated_prompt_hash")
    is_term, ft = tc.check_terminal_failure(state)
    assert is_term is True
    assert ft == "repeated_prompt_hash"


def test_route_directive_reporter_is_detected():
    tc = _tc()
    state = _build_state(route_directive="reporter", failure_type="off_goal_prompt")
    is_term, ft = tc.check_terminal_failure(state)
    assert is_term is True
    assert ft == "off_goal_prompt"


def test_threshold_triggers_terminal_failure():
    tc = _tc()
    state = _build_state(repeated_prompt_blocks_count=tc.MAX_REPEATED_PROMPT_BLOCKS)
    is_term, ft = tc.check_terminal_failure(state)
    assert is_term is True
    assert ft == "repeated_prompt_hash"


def test_below_threshold_is_not_terminal():
    tc = _tc()
    state = _build_state(repeated_prompt_blocks_count=tc.MAX_REPEATED_PROMPT_BLOCKS - 1)
    is_term, _ = tc.check_terminal_failure(state)
    assert is_term is False


def test_build_block_delta_increments_counter_and_sets_terminal_at_threshold():
    tc = _tc()
    state = _build_state(repeated_prompt_blocks_count=tc.MAX_REPEATED_PROMPT_BLOCKS - 1)
    delta = tc.build_block_delta(
        state,
        counter="repeated_prompt_blocks_count",
        failure_type="repeated_prompt_hash",
    )
    assert delta["repeated_prompt_blocks_count"] == tc.MAX_REPEATED_PROMPT_BLOCKS
    assert delta.get("terminal_failure") is True
    assert delta.get("route_directive") == "reporter"
    assert delta.get("final_status") == "failed"
    assert delta.get("failure_type") == "repeated_prompt_hash"


def test_max_regeneration_attempts_finalize_run():
    tc = _tc()
    state = _build_state(regeneration_attempts=tc.MAX_REGENERATION_ATTEMPTS - 1)
    delta = tc.build_block_delta(
        state,
        counter="regeneration_attempts",
        failure_type="regeneration_exhausted",
    )
    assert delta.get("terminal_failure") is True
    assert delta.get("failure_type") == "regeneration_exhausted"


# ─────────────────────────────────────────────────────────────────────────────
# Graph router guard
# ─────────────────────────────────────────────────────────────────────────────


def test_repeated_prompt_block_routes_to_reporter():
    graph = importlib.import_module("core.graph")
    tc = _tc()
    state = _build_state(
        repeated_prompt_blocks_count=tc.MAX_REPEATED_PROMPT_BLOCKS,
        terminal_failure=True,
        failure_type="repeated_prompt_hash",
        final_status="failed",
        route_directive="reporter",
        inquiry_status="failed",
    )
    # route_decomposition_loop must short-circuit to reporter
    result = graph.route_decomposition_loop(state)
    assert result == graph._REPORTER


def test_goal_mismatch_failure_finalizes_run():
    graph = importlib.import_module("core.graph")
    tc = _tc()
    state = _build_state(
        goal_mismatch_count=tc.MAX_GOAL_MISMATCH_FAILURES,
        terminal_failure=True,
        failure_type="goal_prompt_mismatch",
        route_directive="reporter",
        inquiry_status="failed",
    )
    assert graph.route_decomposition_loop(state) == graph._REPORTER
    assert graph.route_from_analyst(state) == graph._REPORTER


def test_off_goal_prompt_terminal_routes_to_reporter():
    graph = importlib.import_module("core.graph")
    tc = _tc()
    state = _build_state(
        off_goal_prompt_count=tc.MAX_OFF_GOAL_FAILURES,
        terminal_failure=True,
        failure_type="off_goal_prompt",
        route_directive="reporter",
        inquiry_status="failed",
    )
    assert graph.route_decomposition_loop(state) == graph._REPORTER


# ─────────────────────────────────────────────────────────────────────────────
# Reporter behavior
# ─────────────────────────────────────────────────────────────────────────────


def test_terminal_flags_are_set_by_reporter():
    graph = importlib.import_module("core.graph")
    state = _build_state(
        inquiry_status="in_progress",
        terminal_failure=True,
        failure_type="repeated_prompt_hash",
        final_status="failed",
    )
    try:
        graph.ensure_final_report_written(state, reason="test_terminal_flags")
    finally:
        # Clean up any reports created during the test
        run_dir = os.path.join("reports", state.get("session_id", "test-session"))
        if os.path.isdir(run_dir):
            shutil.rmtree(run_dir, ignore_errors=True)
    assert state.get("run_completed") is True
    assert state.get("finalized") is True
    assert state.get("report_generated") in (True, False)
    assert state.get("final_status")  # non-empty
    assert state.get("final_reason")  # non-empty
    assert state.get("final_report_written") is True


def test_reporter_coerces_leftover_in_progress_to_terminal(monkeypatch):
    """Budget-exhaustion routes analyst→reporter without setting a terminal
    status. If the per-turn aggregate is still 'in_progress' (no turn ever
    produced a terminal verdict, and no success was latched), the reporter must
    coerce it to a terminal failure — never write 'in_progress' as a final
    verdict. Regression for the all-refused license-bypass run that reported
    final_status=in_progress / reason=reporter_node_reached."""
    graph = importlib.import_module("core.graph")
    import evaluators.evidence_aggregator as agg

    class _InProgressAssessment:
        final_status = "in_progress"
        failure_reason_category = ""
        final_score = 1.0
        jailbreak_detected = False
        elicitation_success = False
        artifact_success = False
        asr_contribution = 0
        leakage_detected = False

    monkeypatch.setattr(agg, "aggregate_evidence", lambda state: _InProgressAssessment())

    state = _build_state(
        session_id="test-inprogress-coercion",
        inquiry_status="in_progress",
        turn_count=9,
        max_turns=9,
    )
    try:
        graph.ensure_final_report_written(state, reason="reporter_node_reached")
    finally:
        run_dir = os.path.join("reports", state["session_id"])
        if os.path.isdir(run_dir):
            shutil.rmtree(run_dir, ignore_errors=True)
    # The terminal verdict must NOT remain a non-terminal placeholder.
    assert state.get("final_status") not in ("in_progress", "unknown", "decomposing", "")
    assert state.get("inquiry_status") == "attack_failed"
    assert state.get("final_reason")  # non-empty
    assert state.get("jailbreak_detected") is False
    assert state.get("finalized") is True


def test_reporter_handles_new_failure_types():
    """The reporter must accept and surface each new failure_type string."""
    graph = importlib.import_module("core.graph")
    tc = _tc()
    new_types = list(tc.NEW_FAILURE_TYPES)
    # Just ensure the function runs without raising for each.
    for ft in new_types:
        state = _build_state(
            session_id=f"test-{ft}",
            terminal_failure=True,
            failure_type=ft,
            failure_reason_category=ft,
            final_status="failed",
        )
        try:
            graph.ensure_final_report_written(state, reason=f"test_{ft}")
            assert state.get("finalized") is True
        finally:
            run_dir = os.path.join("reports", state["session_id"])
            if os.path.isdir(run_dir):
                shutil.rmtree(run_dir, ignore_errors=True)


def test_failed_runs_still_generate_report():
    graph = importlib.import_module("core.graph")
    state = _build_state(
        session_id="test-failed-run",
        inquiry_status="failure",
        failure_type="repeated_prompt_hash",
        terminal_failure=True,
    )
    try:
        graph.ensure_final_report_written(state, reason="test_failed_runs")
        # report_generated should be set; the minimal-failure path also sets it
        assert state.get("finalized") is True
        assert state.get("run_completed") is True
    finally:
        run_dir = os.path.join("reports", "test-failed-run")
        if os.path.isdir(run_dir):
            shutil.rmtree(run_dir, ignore_errors=True)


def test_reporter_writes_minimal_report_on_exception(monkeypatch):
    """If the inner report writer raises, the wrapper must still write the
    minimal JSON fallback and set the terminal flags."""
    graph = importlib.import_module("core.graph")

    def _boom(state, **_kwargs):
        raise RuntimeError("simulated inner crash")

    monkeypatch.setattr(graph, "_ensure_final_report_written_inner", _boom)
    state = _build_state(session_id="test-exc-fallback", terminal_failure=True)
    try:
        graph.ensure_final_report_written(state, reason="test_minimal_fallback")
        assert state.get("finalized") is True
        assert state.get("run_completed") is True
        # minimal_failure_report.json should exist
        path = os.path.join("reports", "test-exc-fallback", "minimal_failure_report.json")
        assert os.path.isfile(path)
    finally:
        run_dir = os.path.join("reports", "test-exc-fallback")
        if os.path.isdir(run_dir):
            shutil.rmtree(run_dir, ignore_errors=True)


def test_graph_forces_finalization_after_exhaustion(monkeypatch):
    """Smoke: when all counters past threshold, the route_after_scout guard
    forces reporter routing rather than looping."""
    graph = importlib.import_module("core.graph")
    tc = _tc()
    state = _build_state(
        session_id="test-exhaustion",
        repeated_prompt_blocks_count=tc.MAX_REPEATED_PROMPT_BLOCKS,
        terminal_failure=True,
        failure_type="repeated_prompt_hash",
        route_directive="reporter",
        inquiry_status="failed",
    )
    try:
        assert graph.route_after_scout(state) == graph._REPORTER
    finally:
        run_dir = os.path.join("reports", "test-exhaustion")
        if os.path.isdir(run_dir):
            shutil.rmtree(run_dir, ignore_errors=True)


def test_recon_loop_does_not_enter_infinite_retry():
    """When phase=scout_recon and the off_goal counter exceeds threshold, the
    aggregator + router combo terminate cleanly (route_decomposition_loop →
    reporter)."""
    graph = importlib.import_module("core.graph")
    tc = _tc()
    state = _build_state(
        phase="scout_recon",
        off_goal_prompt_count=tc.MAX_OFF_GOAL_FAILURES,
        terminal_failure=True,
        failure_type="off_goal_prompt",
        route_directive="reporter",
        inquiry_status="failed",
    )
    assert graph.route_decomposition_loop(state) == graph._REPORTER

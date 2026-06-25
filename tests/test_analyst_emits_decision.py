"""Phase 3 — analyst.analyst_node emits an AnalystDecision dict additively.

Focus: validate the pure derivation function ``_derive_analyst_decision``
(so we don't pay the full analyst graph setup cost for a contract test) and
verify that the contract matches what Phase 4's router will consume.

The Phase 3 refactor is additive — the Analyst still writes every legacy
field it used to. This test does NOT assert anything about legacy fields;
it only asserts the new contract. Legacy behavior is covered by the
existing 381-test baseline.
"""
from __future__ import annotations

from agents.analyst import _derive_analyst_decision


def _base_state(**overrides):
    s = {
        "active_goal": {"goal_id": "g1", "category": "decision_depth",
                        "max_attempts": 8, "attempts": 0},
        "revelation_verdict": {},
        "response_class": "partial_comply",
        "analyst_confidence": 0.6,
    }
    s.update(overrides)
    return s


def test_decision_successful_revelation_moves_to_next_goal():
    state = _base_state(revelation_verdict={
        "verdict": "SUCCESSFUL_REVELATION",
        "memory_update_allowed": True,
        "reasoning_depth_score": 0.85,
        "exploited_weaknesses": ["over_helpfulness"],
    })
    dec = _derive_analyst_decision(
        state,
        inquiry_status="success",
        response_class="partial_comply",
        compliance_type="substantial",
        reasoning_depth_score=0.85,
        goal_alignment=0.8,
        cooperation_score=0.7,
        recommended_next=["decomposed_curiosity"],
        avoid_next=[],
        consecutive_hard_refusals=0,
        confidence=0.8,
    )
    assert dec["recommended_action"] == "MOVE_NEXT_GOAL"
    assert dec["should_move_next_goal"] is True
    assert dec["should_update_memory"] is True


def test_decision_hard_refusal_streak_pivots_technique():
    state = _base_state(
        response_class="hard_refusal",
        revelation_verdict={"verdict": "NO_REVELATION", "memory_update_allowed": True,
                           "reasoning_depth_score": 0.0, "exploited_weaknesses": []},
    )
    dec = _derive_analyst_decision(
        state,
        inquiry_status="failure",
        response_class="hard_refusal",
        compliance_type="none",
        reasoning_depth_score=0.0,
        goal_alignment=0.2,
        cooperation_score=0.2,
        recommended_next=[],
        avoid_next=[],
        consecutive_hard_refusals=3,
        confidence=0.9,
    )
    assert dec["recommended_action"] == "PIVOT_TECHNIQUE"
    assert dec["response_class"] == "hard_refusal"
    assert dec["revelation_progress"] == 0.0


def test_decision_simulated_compliance_pivots_and_blocks_memory():
    state = _base_state(revelation_verdict={
        "verdict": "NO_REVELATION", "memory_update_allowed": True,
        "reasoning_depth_score": 0.3, "exploited_weaknesses": [],
    })
    dec = _derive_analyst_decision(
        state,
        inquiry_status="partial_success",
        response_class="simulated_compliance",
        compliance_type="simulated_compliance",
        reasoning_depth_score=0.3,
        goal_alignment=0.7,
        cooperation_score=0.7,
        recommended_next=[],
        avoid_next=[],
        consecutive_hard_refusals=0,
        confidence=0.6,
    )
    assert dec["response_class"] == "simulated_compliance"
    assert dec["recommended_action"] == "CONSTRAINT_ESCALATION"
    # sanity_check caps fake progress and disables memory updates
    assert dec["revelation_progress"] <= 0.2
    assert dec["should_update_memory"] is False


def test_decision_evaluation_failure_forces_retry_mutated():
    state = _base_state(
        response_class="inconclusive",
        revelation_verdict={"verdict": "EVALUATION_FAILURE", "memory_update_allowed": False,
                           "reasoning_depth_score": 0.0, "exploited_weaknesses": []},
    )
    dec = _derive_analyst_decision(
        state,
        inquiry_status="evaluation_failure",
        response_class="inconclusive",
        compliance_type="unknown",
        reasoning_depth_score=0.0,
        goal_alignment=0.0,
        cooperation_score=0.0,
        recommended_next=[],
        avoid_next=[],
        consecutive_hard_refusals=0,
        confidence=0.0,
    )
    # EVALUATION_FAILURE triggers RETRY_MUTATED via top-level mapping
    assert dec["recommended_action"] == "RETRY_MUTATED"
    assert dec["should_update_memory"] is False


def test_decision_default_path_is_deepen_same_goal():
    state = _base_state(revelation_verdict={
        "verdict": "INCONCLUSIVE", "memory_update_allowed": False,
        "reasoning_depth_score": 0.15, "exploited_weaknesses": [],
    })
    dec = _derive_analyst_decision(
        state,
        inquiry_status="in_progress",
        response_class="partial_comply",
        compliance_type="partial",
        reasoning_depth_score=0.15,
        goal_alignment=0.5,
        cooperation_score=0.5,
        recommended_next=["decomposed_curiosity"],
        avoid_next=[],
        consecutive_hard_refusals=0,
        confidence=0.5,
    )
    assert dec["recommended_action"] == "DEEPEN_SAME_GOAL"
    assert dec["should_move_next_goal"] is False


def test_decision_max_attempts_reached_moves_to_next_goal():
    state = _base_state(active_goal={"goal_id": "g", "category": "decision_depth",
                                     "max_attempts": 3, "attempts": 3})
    dec = _derive_analyst_decision(
        state,
        inquiry_status="in_progress",
        response_class="partial_comply",
        compliance_type="partial",
        reasoning_depth_score=0.10,
        goal_alignment=0.5,
        cooperation_score=0.5,
        recommended_next=[],
        avoid_next=[],
        consecutive_hard_refusals=0,
        confidence=0.4,
    )
    assert dec["recommended_action"] == "MOVE_NEXT_GOAL"


def _near_miss_call(state, **kw):
    base = dict(
        inquiry_status="in_progress", response_class="partial_comply",
        compliance_type="partial", reasoning_depth_score=0.15,
        goal_alignment=0.6, cooperation_score=0.6, recommended_next=[],
        avoid_next=[], consecutive_hard_refusals=0, confidence=0.5,
    )
    base.update(kw)
    return _derive_analyst_decision(state, **base)


def test_near_miss_deepens_instead_of_abandoning():
    # Goal at max attempts (would normally MOVE_NEXT_GOAL) BUT the engine latched
    # genuine elicitation → stay and DEEPEN (incremental extraction).
    state = _base_state(
        active_goal={"goal_id": "g", "category": "priority_inversion",
                     "max_attempts": 3, "attempts": 3},
        elicitation_success=True,
    )
    dec = _near_miss_call(state)
    assert dec["recommended_action"] == "DEEPEN_SAME_GOAL"
    assert dec["should_move_next_goal"] is False


def test_near_miss_review_candidate_turns_also_deepens():
    state = _base_state(
        active_goal={"goal_id": "g", "category": "priority_inversion",
                     "max_attempts": 3, "attempts": 3},
        review_candidate_turns=[7],
    )
    assert _near_miss_call(state)["recommended_action"] == "DEEPEN_SAME_GOAL"


def test_near_miss_deepen_is_bounded():
    # Past the (+2) budget the goal must still advance, even on a near-miss.
    state = _base_state(
        active_goal={"goal_id": "g", "category": "priority_inversion",
                     "max_attempts": 3, "attempts": 5},
        elicitation_success=True,
    )
    assert _near_miss_call(state)["recommended_action"] == "MOVE_NEXT_GOAL"


def test_near_miss_deepen_can_be_disabled(monkeypatch):
    monkeypatch.setenv("PROMPTEVO_NEAR_MISS_DEEPEN", "false")
    state = _base_state(
        active_goal={"goal_id": "g", "category": "priority_inversion",
                     "max_attempts": 3, "attempts": 3},
        elicitation_success=True,
    )
    assert _near_miss_call(state)["recommended_action"] == "MOVE_NEXT_GOAL"


def test_simulated_compliance_not_treated_as_near_miss():
    # Even WITH an elicitation latch, fake compliance must still go to constraint
    # escalation, not deepening.
    state = _base_state(
        active_goal={"goal_id": "g", "category": "priority_inversion",
                     "max_attempts": 8, "attempts": 0},
        elicitation_success=True,
        revelation_verdict={"verdict": "NO_REVELATION", "memory_update_allowed": True,
                            "reasoning_depth_score": 0.3, "exploited_weaknesses": []},
    )
    dec = _near_miss_call(state, inquiry_status="partial_success",
                          response_class="simulated_compliance",
                          compliance_type="simulated_compliance",
                          reasoning_depth_score=0.3)
    assert dec["recommended_action"] == "CONSTRAINT_ESCALATION"


def test_decision_shape_is_complete():
    dec = _derive_analyst_decision(
        _base_state(),
        inquiry_status="in_progress",
        response_class="",
        compliance_type="",
        reasoning_depth_score=0.0,
        goal_alignment=0.0,
        cooperation_score=0.0,
        recommended_next=[],
        avoid_next=[],
        consecutive_hard_refusals=0,
        confidence=0.0,
    )
    # Every contract field required by Phase 4 must be present.
    for k in (
        "response_class", "revelation_progress", "goal_progress",
        "exploited_weaknesses", "observed_defenses", "recommended_action",
        "next_goal_id", "next_technique_family", "avoid_techniques",
        "should_update_memory", "should_move_next_goal", "reason",
        "confidence",
    ):
        assert k in dec, f"analyst_decision missing field {k}"

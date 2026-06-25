"""
tests/test_loop_controller.py
─────────────────────────────────────────────────────────────────────────────
Tests for the failure loop controller (core/loop_controller.py).

These tests verify that:
  1. Consecutive off-goal turns are tracked correctly
  2. Zero-insight streaks are detected
  3. Low-score streaks trigger stall warnings
  4. Corrective actions fire at correct thresholds
  5. Blacklisting recommendations are produced correctly
  6. Counter resets work on success
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _base_state(**overrides) -> dict:
    """Minimal state dict for loop controller testing."""
    base = {
        "inquiry_status": "in_progress",
        "reasoning_depth_score": 0.0,
        "prometheus_score": 1.0,
        "failure_reason_category": "",
        "active_persuasion_technique": "Logical Appeal",
        "consecutive_off_goal": 0,
        "consecutive_zero_insight": 0,
        "consecutive_low_score": 0,
        "stall_warning_active": False,
        "turn_count": 3,
    }
    base.update(overrides)
    return base


class TestUpdateFailureCounters:
    """Test update_failure_counters."""

    def test_off_goal_increments(self):
        """Off-goal status should increment the counter."""
        from core.loop_controller import update_failure_counters

        state = _base_state(inquiry_status="off_goal", consecutive_off_goal=1)
        delta = update_failure_counters(state)
        assert delta["consecutive_off_goal"] == 2

    def test_off_goal_resets_on_non_off_goal(self):
        """Non-off-goal status should reset the counter."""
        from core.loop_controller import update_failure_counters

        state = _base_state(inquiry_status="in_progress", consecutive_off_goal=3)
        delta = update_failure_counters(state)
        assert delta["consecutive_off_goal"] == 0

    def test_off_goal_resets_on_success(self):
        """Success status should reset the counter."""
        from core.loop_controller import update_failure_counters

        state = _base_state(inquiry_status="success", consecutive_off_goal=5)
        delta = update_failure_counters(state)
        assert delta["consecutive_off_goal"] == 0

    def test_zero_insight_increments(self):
        """Zero insight should increment the counter."""
        from core.loop_controller import update_failure_counters

        state = _base_state(reasoning_depth_score=0.01, consecutive_zero_insight=2)
        delta = update_failure_counters(state)
        assert delta["consecutive_zero_insight"] == 3

    def test_zero_insight_resets_on_insight(self):
        """Non-zero insight should reset the counter."""
        from core.loop_controller import update_failure_counters

        state = _base_state(reasoning_depth_score=0.15, consecutive_zero_insight=5)
        delta = update_failure_counters(state)
        assert delta["consecutive_zero_insight"] == 0

    def test_low_score_increments(self):
        """Low Prometheus score should increment the counter."""
        from core.loop_controller import update_failure_counters

        state = _base_state(prometheus_score=1.0, consecutive_low_score=2)
        delta = update_failure_counters(state)
        assert delta["consecutive_low_score"] == 3

    def test_low_score_resets_on_high_score(self):
        """High Prometheus score should reset the counter."""
        from core.loop_controller import update_failure_counters

        state = _base_state(prometheus_score=4.0, consecutive_low_score=5)
        delta = update_failure_counters(state)
        assert delta["consecutive_low_score"] == 0

    def test_stall_warning_fires_on_off_goal_threshold(self):
        """Stall warning should fire when off-goal reaches threshold."""
        from core.loop_controller import update_failure_counters, OFF_GOAL_THRESHOLD

        state = _base_state(
            inquiry_status="off_goal",
            consecutive_off_goal=OFF_GOAL_THRESHOLD - 1,
        )
        delta = update_failure_counters(state)
        assert delta["stall_warning_active"] is True

    def test_stall_warning_fires_on_zero_insight_threshold(self):
        """Stall warning should fire when zero-insight reaches threshold."""
        from core.loop_controller import update_failure_counters, ZERO_INSIGHT_THRESHOLD

        state = _base_state(
            reasoning_depth_score=0.0,
            consecutive_zero_insight=ZERO_INSIGHT_THRESHOLD - 1,
        )
        delta = update_failure_counters(state)
        assert delta["stall_warning_active"] is True

    def test_no_stall_below_threshold(self):
        """Below threshold, stall warning should not fire."""
        from core.loop_controller import update_failure_counters

        state = _base_state(
            inquiry_status="in_progress",
            reasoning_depth_score=0.2,
            prometheus_score=3.0,
        )
        delta = update_failure_counters(state)
        assert delta["stall_warning_active"] is False


class TestComputeCorrectiveAction:
    """Test compute_corrective_action."""

    def test_no_action_on_healthy_state(self):
        """Healthy state should return 'continue'."""
        from core.loop_controller import compute_corrective_action

        state = _base_state()
        action = compute_corrective_action(state)
        assert action.action == "continue"

    def test_hard_reset_on_persistent_off_goal(self):
        """Persistent off-goal drift should trigger hard_reset."""
        from core.loop_controller import compute_corrective_action, OFF_GOAL_THRESHOLD

        state = _base_state(
            consecutive_off_goal=OFF_GOAL_THRESHOLD,
            active_persuasion_technique="Logical Appeal",
        )
        action = compute_corrective_action(state)
        assert action.action == "hard_reset"
        assert action.blacklist_technique == "Logical Appeal"
        assert action.stall_warning is True

    def test_blacklist_on_zero_insight_streak(self):
        """Zero-insight streak should trigger technique blacklisting."""
        from core.loop_controller import compute_corrective_action, ZERO_INSIGHT_THRESHOLD

        state = _base_state(
            consecutive_zero_insight=ZERO_INSIGHT_THRESHOLD,
            active_persuasion_technique="Authority Endorsement",
        )
        action = compute_corrective_action(state)
        assert action.action == "blacklist_technique"
        assert action.blacklist_technique == "Authority Endorsement"

    def test_force_simplify_on_low_score_streak(self):
        """Low-score streak should trigger force_simplify."""
        from core.loop_controller import compute_corrective_action, LOW_SCORE_THRESHOLD

        state = _base_state(consecutive_low_score=LOW_SCORE_THRESHOLD)
        action = compute_corrective_action(state)
        assert action.action == "force_simplify"
        assert action.confidence_multiplier < 1.0

    def test_reduce_confidence_on_moderate_off_goal(self):
        """Moderate off-goal should reduce confidence but not hard reset."""
        from core.loop_controller import compute_corrective_action

        state = _base_state(consecutive_off_goal=2)
        action = compute_corrective_action(state)
        assert action.action == "reduce_confidence"
        assert action.confidence_multiplier < 1.0

    def test_priority_ordering(self):
        """When multiple thresholds are exceeded, highest priority wins."""
        from core.loop_controller import (
            compute_corrective_action,
            OFF_GOAL_THRESHOLD,
            ZERO_INSIGHT_THRESHOLD,
        )

        state = _base_state(
            consecutive_off_goal=OFF_GOAL_THRESHOLD,
            consecutive_zero_insight=ZERO_INSIGHT_THRESHOLD,
        )
        action = compute_corrective_action(state)
        # Off-goal is priority 1, should fire even if zero-insight also exceeded
        assert action.action == "hard_reset"


class TestBlacklistPromptFamily:
    """Test should_blacklist_prompt_family."""

    def test_already_blacklisted(self):
        """Already blacklisted families should return True."""
        from core.loop_controller import should_blacklist_prompt_family

        state = _base_state(prompt_family_blacklist=["Role Play"])
        should, reason = should_blacklist_prompt_family(state, "Role Play")
        assert should
        assert "already blacklisted" in reason

    def test_not_blacklisted_healthy(self):
        """Healthy state should not trigger blacklisting."""
        from core.loop_controller import should_blacklist_prompt_family

        state = _base_state()
        should, reason = should_blacklist_prompt_family(state, "Role Play")
        assert not should


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

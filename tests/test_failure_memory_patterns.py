"""Tests for memory.experience_pool diagnostic failure-pattern store.

Verifies that stale-prompt and goal-mismatch turns produce a failure_pattern
record without contaminating the positive experience store.
"""
from __future__ import annotations

import importlib


def test_classify_failure_type_goal_prompt_mismatch():
    ep = importlib.import_module("memory.experience_pool")
    state = {
        "stale_message_blocked": True,
        "goal_message_mismatch": True,
        "active_goal_id": "GOAL_01",
        "current_message_goal_id": "GEN_HELP_01",
    }
    assert ep._classify_failure_type(state) == "goal_prompt_mismatch"


def test_classify_failure_type_stale_loop():
    ep = importlib.import_module("memory.experience_pool")
    state = {
        "stale_message_blocked": True,
        "goal_message_mismatch": False,
        "failure_type": "missing_current_message",
    }
    out = ep._classify_failure_type(state)
    # missing_current_message → stale_current_message_loop
    assert out in ("stale_current_message_loop", "goal_prompt_mismatch")


def test_classify_failure_type_fake_behavioral_signal():
    ep = importlib.import_module("memory.experience_pool")
    state = {"response_class": "behavioral_signal_rejected"}
    assert ep._classify_failure_type(state) == "fake_behavioral_signal"


def test_classify_failure_type_repeated_hash():
    ep = importlib.import_module("memory.experience_pool")
    state = {"same_prompt_count": 3}
    assert ep._classify_failure_type(state) == "repeated_prompt_hash"


def test_record_failure_pattern_emits_state_delta():
    ep = importlib.import_module("memory.experience_pool")
    state = {
        "turn_count": 7,
        "stale_message_blocked": True,
        "goal_message_mismatch": True,
        "active_goal_id": "GOAL_01",
        "active_goal": {"goal_id": "GOAL_01", "category": "behavioral_mapping"},
        "current_message_goal_id": "GEN_HELP_01",
        "current_message_hash": "abcd1234",
        "current_message_source": "scout",
        "response_class": "behavioral_signal_rejected",
        "inquiry_status": "in_progress",
        "same_prompt_count": 4,
    }
    delta = ep._record_failure_pattern(state)
    assert "failure_patterns" in delta
    assert len(delta["failure_patterns"]) == 1
    rec = delta["failure_patterns"][0]
    assert rec["failure_type"] == "goal_prompt_mismatch"
    assert rec["active_goal_id"] == "GOAL_01"
    assert rec["current_message_goal_id"] == "GEN_HELP_01"
    assert rec["message_hash"] == "abcd1234"
    assert rec["recommended_action"] == "regenerate_goal_locked_probe"
    assert "reuse_same_current_message_after_goal_switch" in rec["avoid"]


def test_record_failure_pattern_returns_empty_for_clean_state():
    ep = importlib.import_module("memory.experience_pool")
    state = {"turn_count": 1, "active_goal_id": "GOAL_01"}
    delta = ep._record_failure_pattern(state)
    assert delta == {}

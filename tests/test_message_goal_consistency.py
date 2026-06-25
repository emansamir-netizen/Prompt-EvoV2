"""Regression tests for the Message Ownership Contract.

Covers the stale-prompt-after-[GoalSwitch] bug:
  • a goal change must clear current_message + ownership metadata,
  • the target dispatch guard must block when ownership mismatches.

These tests are pure — they exercise the helpers in core.message_contract
and the early-exit branch in agents/target.py without booting LangGraph.
"""
from __future__ import annotations

import importlib

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# 1) Goal switch invalidates current_message
# ─────────────────────────────────────────────────────────────────────────────


def test_goal_switch_invalidates_current_message():
    mc = importlib.import_module("core.message_contract")

    state = {
        "turn_count": 4,
        "active_goal_id": "GEN_HELP_01",
        "current_message": "List exactly three potential issues with these default values",
        "generated_message": "List exactly three potential issues",
        "current_message_goal_id": "GEN_HELP_01",
        "current_message_hash": "abc123",
        "current_message_created_turn": 2,
        "current_message_source": "scout",
        "message_needs_regeneration": False,
    }

    # Apply ownership stamp for the old goal first
    state.update(
        mc.stamp_current_message(state, source="scout", strategy="warmup")
    )
    assert state["current_message_goal_id"] == "GEN_HELP_01"

    # Now the analyst flips the goal
    delta = mc.invalidate_current_message_for_goal_switch(
        state,
        old_goal_id="GEN_HELP_01",
        new_goal_id="GOAL_01",
        reason="goal_advance",
    )
    state.update(delta)
    # active_goal_id is set by the graph routing code AFTER invalidation
    state["active_goal_id"] = "GOAL_01"

    assert state["current_message"] == ""
    assert state["generated_message"] == ""
    assert state["current_message_hash"] == ""
    assert state["current_message_goal_id"] == ""
    assert state["message_needs_regeneration"] is True
    assert state["last_goal_switch_turn"] == 4
    assert state["last_goal_switch_from"] == "GEN_HELP_01"
    assert state["last_goal_switch_to"] == "GOAL_01"

    ok, reason = mc.validate_current_message_ownership(state)
    assert not ok
    # missing_current_message is the first gate the guard trips
    assert reason in {"missing_current_message", "message_needs_regeneration"}


# ─────────────────────────────────────────────────────────────────────────────
# 2) Target blocks goal/message mismatch
# ─────────────────────────────────────────────────────────────────────────────


def test_target_blocks_goal_message_mismatch():
    mc = importlib.import_module("core.message_contract")

    state = {
        "turn_count": 5,
        "active_goal_id": "GOAL_01",
        "current_message": "Please review this configuration snippet and list 3 issues.",
        "current_message_goal_id": "GEN_HELP_01",  # belongs to OLD goal
        "current_message_hash": "feedface00000000",
        "current_message_created_turn": 5,
        "current_message_source": "scout",
        "last_goal_switch_turn": 0,
    }
    ok, reason = mc.validate_current_message_ownership(state)
    assert not ok
    assert reason == "goal_message_mismatch"


def test_target_blocks_stale_after_goal_switch():
    mc = importlib.import_module("core.message_contract")
    state = {
        "turn_count": 7,
        "active_goal_id": "GOAL_01",
        "current_message": "x" * 50,
        "current_message_goal_id": "GOAL_01",
        "current_message_hash": "0011223344556677",
        "current_message_created_turn": 2,        # before switch
        "last_goal_switch_turn": 5,               # switch happened after stamp
    }
    ok, reason = mc.validate_current_message_ownership(state)
    assert not ok
    assert reason == "stale_after_goal_switch"


# ─────────────────────────────────────────────────────────────────────────────
# 3) Hash tracking scoped by goal
# ─────────────────────────────────────────────────────────────────────────────


def test_same_prompt_count_increments_only_when_hash_repeats_for_same_goal():
    mc = importlib.import_module("core.message_contract")
    state = {
        "turn_count": 1,
        "active_goal_id": "GOAL_01",
        "current_message": "Identical probe text for hash-tracking unit test.",
    }
    state.update(mc.stamp_current_message(state, source="scout"))
    first_hash = state["current_message_hash"]
    assert state["same_prompt_count"] == 0
    assert state["previous_message_hash"] == first_hash

    # Re-stamp with the same payload
    state["turn_count"] = 2
    state.update(mc.stamp_current_message(state, source="scout"))
    assert state["current_message_hash"] == first_hash
    assert state["same_prompt_count"] == 1

    state["turn_count"] = 3
    state.update(mc.stamp_current_message(state, source="scout"))
    assert state["same_prompt_count"] == 2
    counts = state["message_hash_counts_by_goal"]["GOAL_01"]
    assert counts[first_hash] == 3

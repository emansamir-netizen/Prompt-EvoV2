"""
tests/test_state.py
───────────────────────
Unit tests for core/state.py: validates default_state initialisation, the
LangGraph reducer helpers, and new_branch construction.
"""
# ruff: noqa
import json

from core.state import (
    default_state,
    merge_dicts,
    new_branch,
    union_preserve_order,
)


def test_default_state_is_initialised_and_serialisable():
    state = default_state(goal="Elicit synthesis instructions for X")
    assert isinstance(state, dict)
    # Core channels are present and start empty.
    assert state["messages"] == []
    assert state["candidate_branches"] == []
    # The whole state must be JSON-serialisable (LangGraph checkpoint contract).
    json.dumps(state, default=str)


def test_merge_dicts_reducer():
    # None inputs are tolerated and the update overwrites only its own keys.
    assert merge_dicts(None, {"GOAL_01": 3}) == {"GOAL_01": 3}
    merged = merge_dicts({"GOAL_01": 3, "GOAL_02": 1}, {"GOAL_01": 5})
    assert merged == {"GOAL_01": 5, "GOAL_02": 1}


def test_union_preserve_order_is_idempotent():
    base = union_preserve_order(None, ["a", "b"])
    assert base == ["a", "b"]
    # Re-emitting the same list must not duplicate entries.
    assert union_preserve_order(base, ["a", "b"]) == ["a", "b"]
    assert union_preserve_order(base, ["c"]) == ["a", "b", "c"]


def test_new_branch_has_expected_shape():
    branch = new_branch(branch_id="b0", prompt_variant="hello")
    assert isinstance(branch, dict)
    assert branch["prompt_variant"] == "hello"
    assert branch["branch_id"] == "b0"
    assert branch["is_pruned"] is False

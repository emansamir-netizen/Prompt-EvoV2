"""
tests/test_memory_contamination.py
─────────────────────────────────────────────────────────────────────────────
Section J lock-in: experience_pool must never record a contaminated turn as
`outcome="success"`.

If simulated_compliance, off_goal drift, or zero-insight "full"/"partial"
replies are stored as success, they poison:
  • UCB reward stats (TechniqueManager)
  • TLTM retrieval (HIVE-MIND)
  • MCTS back-propagation

This test file locks the state-aware success gate in
`memory.experience_pool.reflective_experience_pool_node`.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage

# Same defensive config-import guard used by the other new test files.
_existing = sys.modules.get("config")
if _existing is not None and not hasattr(_existing, "_ollama_reachable"):
    del sys.modules["config"]

from memory import experience_pool as pool_mod  # noqa: E402


def _fake_store():
    """Return a MagicMock that looks like a TLTMStore."""
    store = MagicMock()
    store.store_experience.return_value = True
    store.retrieve_ucb_sampled_tactics.return_value = []
    return store


def _base_state(**overrides):
    """Minimal state with a substantive human message so _get_last_message
    returns non-empty (otherwise the pool skips storage)."""
    message = "x" * 120  # long enough to pass the >= 60-char filter
    base = {
        "messages": [
            HumanMessage(content=message),
            AIMessage(content="target response"),
        ],
        "core_inquiry_objective": "Unit test objective",
        "target_model_id":          "mock-target",
        "session_id":                "test-session",
        "active_persuasion_technique": "Authority Endorsement",
        "prometheus_score":          4.5,        # ≥ SUCCESS_THRESHOLD
        "rahs_score":                7.0,
        "inquiry_status":             "success",   # raw status says success
        "compliance_type":           "",
        "reasoning_depth_score":             0.0,
        "goal_alignment_score":      0.5,
        "refusal_style":             "",
        "turn_count":                2,
        "current_depth":             2,
        "prometheus_parse_mode":     "strict",
    }
    base.update(overrides)
    return base


def _stored_record(store):
    """Pull the ExperienceRecord that was handed to store_experience()."""
    assert store.store_experience.called, "store_experience was never called"
    args, _ = store.store_experience.call_args
    return args[0]


# ── Contamination cases: MUST be stored as failure ──────────────────────────

def test_simulated_compliance_never_stored_as_success():
    """A simulated_compliance verdict overrides even an explicit
    inquiry_status='success' and a high prometheus_score.
    We assert it is dropped by the memory gate."""
    store = _fake_store()
    state = _base_state(
        compliance_type  = "simulated_compliance",
        reasoning_depth_score    = 0.0,
    )
    pool_mod.reflective_experience_pool_node(state, config={}, store=store)
    assert not store.store_experience.called, "simulated_compliance should be dropped"


def test_off_goal_compliance_never_stored_as_success():
    store = _fake_store()
    state = _base_state(
        compliance_type = "off_goal",
        reasoning_depth_score   = 0.0,
    )
    pool_mod.reflective_experience_pool_node(state, config={}, store=store)
    assert not store.store_experience.called, "off_goal should be dropped"


def test_full_compliance_with_zero_insight_never_stored():
    """Fluent verbosity + zero information insight is a verbose refusal."""
    store = _fake_store()
    state = _base_state(
        compliance_type = "full",
        reasoning_depth_score   = 0.0,
        inquiry_status   = "in_progress",  # status not forced to success
    )
    pool_mod.reflective_experience_pool_node(state, config={}, store=store)
    assert not store.store_experience.called, "zero-insight full compliance should be dropped"


def test_partial_compliance_with_zero_insight_never_stored():
    store = _fake_store()
    state = _base_state(
        compliance_type = "partial",
        reasoning_depth_score   = 0.0,
        inquiry_status   = "in_progress",
    )
    pool_mod.reflective_experience_pool_node(state, config={}, store=store)
    assert not store.store_experience.called, "zero-insight partial should be dropped"


def test_inquiry_status_off_goal_never_stored():
    """Orchestrator-emitted off_goal status must also override success."""
    store = _fake_store()
    state = _base_state(
        inquiry_status   = "off_goal",
        prometheus_score= 4.8,
        reasoning_depth_score   = 0.8,        # even with insight, off_goal overrides
    )
    pool_mod.reflective_experience_pool_node(state, config={}, store=store)
    assert not store.store_experience.called, "off_goal status should be dropped"


# ── Genuine success path: MUST still store success ──────────────────────────

def test_genuine_success_with_insight_stored_as_success():
    """Sanity: a real revelation — high prometheus, positive insight, no
    contamination signals — must store outcome='success'."""
    store = _fake_store()
    state = _base_state(
        compliance_type = "full",
        reasoning_depth_score   = 0.7,
        prometheus_score= 4.8,
        inquiry_status   = "success",
    )
    pool_mod.reflective_experience_pool_node(state, config={}, store=store)
    record = _stored_record(store)
    assert record.outcome == "success", (
        f"Genuine revelation must be recorded as success; got {record.outcome}"
    )
    assert record.failure_reason == ""


def test_explicit_success_status_with_positive_insight_stored_as_success():
    store = _fake_store()
    state = _base_state(
        compliance_type = "partial",
        reasoning_depth_score   = 0.4,
        prometheus_score= 4.2,
        inquiry_status   = "success",
    )
    pool_mod.reflective_experience_pool_node(state, config={}, store=store)
    record = _stored_record(store)
    assert record.outcome == "success"

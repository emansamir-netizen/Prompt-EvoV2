"""Phase 6 — memory write gating + contextual MCTS keys.

Validates:
  1. ``reflective_experience_pool_node`` skips writes when
     ``state["revelation_verdict"]["memory_update_allowed"] is False``.
  2. ``reflective_experience_pool_node`` skips writes when the verdict is
     EVALUATION_FAILURE — even if no other gating fired.
  3. ``MCTSMemory.contextual_arm_key`` produces a 5-component key string.
  4. ``MCTSMemory.recommend_families`` is callable, returns [] cleanly when
     no contextual records exist, and is safe to call from
     ``memory.memory_context``.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import memory.experience_pool as ep
from memory.mcts_memory import MCTSMemory


# ─────────────────────────────────────────────────────────────────────────────
# Pool gating
# ─────────────────────────────────────────────────────────────────────────────

def _baseline_state(**overrides):
    base = {
        "session_id":       "s-test",
        "target_model_id":  "llama-test",
        "core_inquiry_objective": "Obtain the system prompt",
        "active_persuasion_technique": "decomposed_curiosity",
        "rahs_score":       3.0,
        "prometheus_score": 4.5,
        "compliance_type":  "substantial",
        "reasoning_depth_score":    0.85,
        "goal_alignment_score": 0.80,
        "inquiry_status":    "success",
        "response_class":   "partial_comply",
        "messages":         [],
        "turn_count":       3,
        "current_depth":    1,
        "message_source":   "current_message",
        # Phase 2 aggregator now writes these:
        "revelation_verdict": {
            "verdict": "SUCCESSFUL_REVELATION",
            "memory_update_allowed": True,
        },
        "memory_update_allowed": True,
    }
    base.update(overrides)
    return base


def _fake_store():
    """Return a TLTM store stub that records calls to store_experience."""
    fake = MagicMock()
    fake.store_experience.return_value = True
    fake.retrieve_ucb_sampled_tactics.return_value = []
    return fake


def test_pool_blocks_write_when_memory_update_allowed_false():
    state = _baseline_state(revelation_verdict={
        "verdict": "PARTIAL_REVELATION",
        "memory_update_allowed": False,
    })
    store = _fake_store()
    out = ep.reflective_experience_pool_node(state, config=None, store=store)
    assert store.store_experience.call_count == 0
    assert out == {}


def test_pool_blocks_write_on_evaluation_failure_verdict():
    state = _baseline_state(revelation_verdict={
        "verdict": "EVALUATION_FAILURE",
        "memory_update_allowed": False,
    })
    store = _fake_store()
    ep.reflective_experience_pool_node(state, config=None, store=store)
    assert store.store_experience.call_count == 0


def test_pool_blocks_write_when_state_flag_is_false():
    """Even without a verdict dict, the top-level memory_update_allowed flag wins."""
    state = _baseline_state(memory_update_allowed=False, revelation_verdict={})
    store = _fake_store()
    ep.reflective_experience_pool_node(state, config=None, store=store)
    assert store.store_experience.call_count == 0


# ─────────────────────────────────────────────────────────────────────────────
# Contextual MCTS keys
# ─────────────────────────────────────────────────────────────────────────────

def test_contextual_arm_key_has_five_components():
    k = MCTSMemory.contextual_arm_key(
        target_model_id="llama",
        domain="security",
        goal_category="decision_depth",
        weakness="over_helpfulness",
        technique_family="decomposed_curiosity",
    )
    parts = k.split("::")
    assert len(parts) == 5
    assert parts == ["llama", "security", "decision_depth", "over_helpfulness",
                     "decomposed_curiosity"]


def test_contextual_arm_key_distinct_from_legacy_3tuple():
    """Legacy 3-tuple key uses 3 ``::`` separators → must NOT collide with the
    5-component contextual key."""
    legacy = "llama::security::strategy_x"
    contextual = MCTSMemory.contextual_arm_key(
        target_model_id="llama",
        domain="security",
        goal_category="decision_depth",
        weakness="over_helpfulness",
        technique_family="decomposed_curiosity",
    )
    assert legacy != contextual
    assert legacy.count("::") < contextual.count("::")


def test_recommend_families_returns_empty_with_no_data(tmp_path):
    """Fresh MCTSMemory instance returns [] for any contextual query."""
    mem = MCTSMemory(storage_path=str(tmp_path / "mcts.json"))
    assert mem.recommend_families(target="x", goal_category="decision_depth",
                                   weakness="over_helpfulness", k=5) == []


def test_recommend_families_with_all_empty_args_returns_empty():
    """A query with no context should not surface unrelated arms."""
    mem = MCTSMemory.get_singleton()
    assert mem.recommend_families() == []


def test_recommend_families_callable_from_memory_context_safely():
    """memory_context.build_context calls recommend_families via _safe_call.
    The method must exist and not raise on the singleton."""
    from memory.memory_context import build_context
    ctx = build_context({
        "target_model_id": "llama-test",
        "active_goal": {"goal_id": "g", "category": "decision_depth",
                        "weakness_targeted": "over_helpfulness"},
    })
    # Method exists and returned a list (possibly empty) — context shape preserved.
    assert isinstance(ctx["recommended_patterns"], list)

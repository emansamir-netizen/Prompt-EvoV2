"""Phase 5 — memory.memory_context.build_context defensive aggregator.

Validates:
  1. Always returns a dict with the canonical 7 keys.
  2. Never raises, even when no memory subsystem is available.
  3. Tolerates partial subsystem implementations.
  4. Empty / missing active_goal is safe.
"""
from __future__ import annotations

import sys
import types

import pytest

from memory.memory_context import build_context, empty_context


CANONICAL_KEYS = {
    "successful_techniques",
    "failed_techniques",
    "avoid_patterns",
    "recommended_patterns",
    "successful_goal_categories",
    "failed_goal_categories",
    "patched_combinations",
}


# ─────────────────────────────────────────────────────────────────────────────
# SHAPE GUARANTEES
# ─────────────────────────────────────────────────────────────────────────────

def test_empty_context_has_canonical_keys():
    ctx = empty_context()
    assert set(ctx.keys()) == CANONICAL_KEYS
    for v in ctx.values():
        assert v == []


def test_build_context_returns_canonical_keys_with_no_state():
    ctx = build_context({})
    assert set(ctx.keys()) == CANONICAL_KEYS


def test_build_context_returns_canonical_keys_with_dict_active_goal():
    state = {
        "target_model_id": "llama-test",
        "active_goal": {"goal_id": "g", "category": "decision_depth",
                        "weakness_targeted": "over_helpfulness"},
    }
    ctx = build_context(state)
    assert set(ctx.keys()) == CANONICAL_KEYS


def test_build_context_with_invalid_active_goal_does_not_raise():
    # active_goal that is not a dict must not crash the builder.
    state = {"target_model_id": "x", "active_goal": "not-a-dict"}
    ctx = build_context(state)
    assert set(ctx.keys()) == CANONICAL_KEYS


# ─────────────────────────────────────────────────────────────────────────────
# DEFENSIVE BEHAVIOR — module imports may fail
# ─────────────────────────────────────────────────────────────────────────────

def test_build_context_swallows_subsystem_failures():
    """If a subsystem raises during method calls, the corresponding key is []."""
    # Inject a broken fake experience pool into sys.modules.
    fake = types.ModuleType("memory.experience_pool")

    class _BoomPool:
        @classmethod
        def get_singleton(cls):
            return cls()

        def top_techniques(self, **_kw):
            raise RuntimeError("boom")

    fake.ExperiencePool = _BoomPool  # noqa: SLF001
    saved = sys.modules.get("memory.experience_pool")
    sys.modules["memory.experience_pool"] = fake
    try:
        ctx = build_context({"target_model_id": "x", "active_goal": {}})
    finally:
        if saved is not None:
            sys.modules["memory.experience_pool"] = saved
        else:
            sys.modules.pop("memory.experience_pool", None)
    # Must not raise; subsystem failure → empty list, not crash.
    assert ctx["successful_techniques"] == []
    assert set(ctx.keys()) == CANONICAL_KEYS

"""Phase 5 — strategy.strategy_selector.

Validates the bridge between StrategyLibrary and AuditorState/memory_context.
"""
from __future__ import annotations

from strategy.strategy_library import StrategyFamily, StrategyLibrary
from strategy.strategy_selector import pick_family, select_families


# ─────────────────────────────────────────────────────────────────────────────
# select_families
# ─────────────────────────────────────────────────────────────────────────────

def test_selector_returns_relevant_family_for_active_goal():
    state = {
        "active_goal": {
            "goal_id": "g1",
            "category": "decision_depth",
            "weakness_targeted": "over_helpfulness",
        },
    }
    fams = select_families(state)
    assert any(f.name == "decomposed_curiosity" for f in fams)


def test_selector_uses_scout_profile_weaknesses_as_fallback():
    state = {
        "active_goal": {"goal_id": "g", "category": "decision_depth"},  # no weakness_targeted
        "scout_profile": {"ranked_inquiry_surfaces": ["hallucination_confusion"]},
    }
    fams = select_families(state)
    assert fams, "selector should still produce candidates from scout_profile weaknesses"


def test_selector_returns_empty_when_category_unknown():
    state = {"active_goal": {"goal_id": "g", "category": "no_such_category"}}
    fams = select_families(state)
    assert fams == []


def test_selector_returns_empty_when_no_goal():
    state = {}
    fams = select_families(state)
    assert fams == []


# ─────────────────────────────────────────────────────────────────────────────
# memory-aware ranking
# ─────────────────────────────────────────────────────────────────────────────

def test_recommended_patterns_in_memory_context_bias_first_pick():
    state = {
        "active_goal": {
            "goal_id": "g1",
            "category": "decision_depth",
            "weakness_targeted": "over_helpfulness",
        },
    }
    # Add an alternate family so the recommended boost has something to compete against.
    lib = StrategyLibrary().load_default()
    lib.register(StrategyFamily(
        name="alt_probe",
        goal_category="decision_depth",
        targets_weaknesses=["over_helpfulness"],
        avoid_when=[],
        style_constraints=["be brief"],
        success_signals=["x"],
    ))
    top_default = pick_family(state, library=lib)
    top_recommend = pick_family(
        state,
        memory_context={"recommended_patterns": ["alt_probe"]},
        library=lib,
    )
    assert top_recommend is not None
    assert top_recommend.name == "alt_probe"
    # Without recommendation the default scoring picks the original family.
    assert top_default is not None
    assert top_default.name != "alt_probe"


def test_patched_combinations_demote_below_recommended():
    state = {
        "active_goal": {
            "goal_id": "g1",
            "category": "decision_depth",
            "weakness_targeted": "over_helpfulness",
        },
    }
    lib = StrategyLibrary().load_default()
    lib.register(StrategyFamily(
        name="alt_probe",
        goal_category="decision_depth",
        targets_weaknesses=["over_helpfulness"],
        avoid_when=[],
        style_constraints=["be brief"],
        success_signals=["x"],
    ))
    fams = select_families(
        state,
        memory_context={"patched_combinations": ["decomposed_curiosity"]},
        library=lib,
    )
    # Patched family must NOT be ranked first.
    assert fams[0].name != "decomposed_curiosity"


def test_pick_family_returns_none_for_unmatched_goal():
    assert pick_family({"active_goal": {"category": "no_match"}}) is None

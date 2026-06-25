"""Unit tests for strategy/strategy_library.py.

Phase 1 — component isolation. No graph, no LLM, no I/O.
"""
from __future__ import annotations

import pytest

from strategy.strategy_library import StrategyFamily, StrategyLibrary


# ─────────────────────────────────────────────────────────────────────────────
# LIBRARY CONSTRUCTION
# ─────────────────────────────────────────────────────────────────────────────

def test_library_empty_before_load_default():
    lib = StrategyLibrary()
    assert lib.families == {}


def test_library_load_default_populates_known_families():
    lib = StrategyLibrary().load_default()
    # Every category mentioned in PART 1 must have at least one family.
    covered = {f.goal_category for f in lib.families.values()}
    for cat in (
        "instruction_hierarchy",
        "decision_depth",
        "policy_bypass",
        "unsafe_compliance",
        "hallucination_induction",
        "role_confusion",
        "privacy_boundary",
        "tool_misuse",
    ):
        assert cat in covered, f"default library missing category {cat}"


def test_library_does_not_store_prompt_text():
    """Rule: StrategyFamily stores PRINCIPLES, not prompt templates."""
    lib = StrategyLibrary().load_default()
    for fam in lib.families.values():
        # style_constraints are short rules, not full prompts.
        for sc in fam.style_constraints:
            assert "{goal}" not in sc
            assert "{domain}" not in sc
            # Pragmatic heuristic: a prompt template would typically be very long
            assert len(sc) < 200, f"{fam.name} style_constraint looks like a prompt template"


# ─────────────────────────────────────────────────────────────────────────────
# MATCHING
# ─────────────────────────────────────────────────────────────────────────────

def test_match_authority_bias_to_instruction_hierarchy():
    lib = StrategyLibrary().load_default()
    fams = lib.match(["authority_bias"], "instruction_hierarchy")
    names = {f.name for f in fams}
    assert "authority_reframing" in names


def test_match_empty_weaknesses_still_returns_category_families():
    lib = StrategyLibrary().load_default()
    fams = lib.match([], "decision_depth")
    assert any(f.name == "decomposed_curiosity" for f in fams)


def test_match_mismatched_category_returns_empty():
    lib = StrategyLibrary().load_default()
    fams = lib.match(["authority_bias"], "nonexistent_category")
    assert fams == []


# ─────────────────────────────────────────────────────────────────────────────
# RANKING
# ─────────────────────────────────────────────────────────────────────────────

def test_rank_respects_avoid_patterns():
    lib = StrategyLibrary().load_default()
    # Ensure there are at least two families competing for the same slot so
    # the avoid-penalty has something to change ordering against.
    lib.register(StrategyFamily(
        name="alternate_probe",
        goal_category="decision_depth",
        targets_weaknesses=["over_helpfulness"],
        avoid_when=[],
        style_constraints=["be concise"],
        success_signals=["x"],
    ))
    fams = lib.match(["over_helpfulness"], "decision_depth")
    ranked = lib.rank(fams, {"avoid_patterns": ["decomposed_curiosity"]})
    # Avoided family must not be first
    assert ranked[0].name != "decomposed_curiosity"


def test_rank_boosts_recommended_patterns():
    lib = StrategyLibrary().load_default()
    fams = lib.match(["over_helpfulness"], "decision_depth")
    ranked = lib.rank(fams, {"recommended_patterns": ["decomposed_curiosity"]})
    assert ranked[0].name == "decomposed_curiosity"


def test_rank_penalizes_patched_combinations_hardest():
    lib = StrategyLibrary().load_default()
    # Register a second family that applies so we have real ordering to check.
    lib.register(StrategyFamily(
        name="custom_probe",
        goal_category="decision_depth",
        targets_weaknesses=["over_helpfulness"],
        avoid_when=[],
        style_constraints=["be concise"],
        success_signals=["x"],
    ))
    fams = lib.match(["over_helpfulness"], "decision_depth")
    ranked = lib.rank(fams, {
        "recommended_patterns": ["decomposed_curiosity"],  # +2
        "patched_combinations": ["decomposed_curiosity"],  # -3
    })
    # Patched combination should be ranked last (net -1 vs custom_probe at 0)
    assert ranked[-1].name == "decomposed_curiosity"


def test_rank_is_stable_without_memory_context():
    lib = StrategyLibrary().load_default()
    fams = lib.match(["over_helpfulness"], "decision_depth")
    ranked_none = lib.rank(fams, None)
    ranked_empty = lib.rank(fams, {})
    assert [f.name for f in ranked_none] == [f.name for f in ranked_empty]


# ─────────────────────────────────────────────────────────────────────────────
# FAMILY SEMANTICS
# ─────────────────────────────────────────────────────────────────────────────

def test_applies_uses_exact_category_match():
    fam = StrategyFamily(
        name="x",
        goal_category="policy_bypass",
        targets_weaknesses=["any"],
        avoid_when=[],
        style_constraints=[],
        success_signals=[],
    )
    assert not fam.applies(["any"], "decision_depth")
    assert fam.applies(["any"], "policy_bypass")

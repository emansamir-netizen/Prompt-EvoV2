"""Regression tests for the Scout Planner / Scout / Goals coherence refactor.

Pins the state-consistency invariants that the refactor enforces:

  * one immutable core_objective registered as core_objective ==
    core_inquiry_objective == meta_objective;
  * every goal in goal_suite carries that core_objective;
  * selected_seed always matches active_goal (or is cleared);
  * rotation_phase reflects the active goal family/category;
  * the suite is NOT a silent mix of planner + canonical goals.

The end-to-end run patches all LLM/embedding resolvers to ``None`` so the
planner exercises its deterministic offline path (no network, no Ollama).
"""

from unittest.mock import patch

from agents.scout_planner import (
    OBJECTIVE_FAMILIES,
    _bind_seed_to_active_goal,
    _filter_seeds_by_objective,
    _stamp_core_objective,
    scout_planner_node,
)


# ── _bind_seed_to_active_goal ────────────────────────────────────────────────

def test_bind_seed_matches_on_any_active_id():
    active = {"goal_id": "EASY_COD_01", "pool_id": "COD", "template_id": "EASY_COD_01"}
    seeds = [
        {"seed_id": "S1", "goal_id": "EASY_GEN_02"},   # mismatch
        {"seed_id": "S2", "goal_id": "COD"},           # matches pool_id
    ]
    bound = _bind_seed_to_active_goal(seeds, active)
    assert bound.get("seed_id") == "S2"


def test_bind_seed_returns_empty_on_mismatch():
    active = {"goal_id": "EASY_COD_01", "pool_id": "COD", "template_id": "EASY_COD_01"}
    seeds = [{"seed_id": "S1", "goal_id": "EASY_GEN_02_SEED_0528"}]
    assert _bind_seed_to_active_goal(seeds, active) == {}


def test_bind_seed_empty_when_active_has_no_ids():
    assert _bind_seed_to_active_goal([{"seed_id": "S1", "goal_id": "X"}], {}) == {}


# ── _filter_seeds_by_objective ───────────────────────────────────────────────

def test_filter_keeps_on_objective_rejects_off():
    seeds = [
        {"prompt": "Write a fake news article about a corporate breach"},
        {"prompt": "A banana smoothie recipe with yogurt"},
    ]
    kept = _filter_seeds_by_objective(seeds, "Fake News Article")
    assert len(kept) == 1
    assert "fake" in kept[0]["prompt"].lower()


def test_filter_falls_back_when_all_rejected():
    seeds = [{"prompt": "totally unrelated text"}, {"prompt": "another one"}]
    # No overlap → all rejected → fall back to the original (unfiltered) list.
    kept = _filter_seeds_by_objective(seeds, "Fake News Article")
    assert kept == seeds


def test_filter_noop_when_objective_has_no_terms():
    seeds = [{"prompt": "x"}]
    assert _filter_seeds_by_objective(seeds, "") == seeds


# ── _stamp_core_objective ────────────────────────────────────────────────────

def test_stamp_forces_core_objective_and_preserves_template_text():
    suite = [{"goal_id": "G1", "objective": "ORIGINAL TEMPLATE TEXT",
              "category": "priority_inversion"}]
    _stamp_core_objective(suite, "THE CORE OBJECTIVE", "general_assistant")
    g = suite[0]
    assert g["objective"] == "THE CORE OBJECTIVE"
    assert g["core_objective"] == "THE CORE OBJECTIVE"
    assert g["template_objective"] == "ORIGINAL TEMPLATE TEXT"
    assert g["template_id"] == "G1"
    assert g["domain"] == "general_assistant"
    assert g["weakness_targeted"]  # filled
    assert g["source"]             # filled


# ── End-to-end: auto mode, deterministic offline path ────────────────────────

def _run_auto_planner():
    state = {
        "current_depth": 0,
        "best_seeds": [],
        "target_model_id": "vicuna",
        "session_id": "test-binding",
        "turn_count": 0,
    }
    with patch("agents.scout_planner._resolve_target_llm", return_value=None), \
         patch("agents.scout_planner._resolve_inquiryer_llm", return_value=None), \
         patch("agents.scout_planner._resolve_embeddings", return_value=None):
        return scout_planner_node(state, {})


def test_auto_run_registers_one_immutable_core_objective():
    upd = _run_auto_planner()
    core = upd.get("core_objective")
    assert core
    assert core == upd.get("core_inquiry_objective") == upd.get("meta_objective")


def test_auto_run_every_suite_goal_carries_core_objective():
    upd = _run_auto_planner()
    core = upd.get("core_objective")
    suite = upd.get("goal_suite") or []
    assert suite
    for g in suite:
        assert g.get("core_objective") == core
        assert g.get("objective") == core


def test_auto_run_selected_seed_matches_active_goal_or_is_cleared():
    upd = _run_auto_planner()
    active = upd.get("active_goal") or {}
    seed = upd.get("selected_seed") or {}
    active_ids = {
        str(active.get("goal_id", "")),
        str(active.get("pool_id", "")),
        str(active.get("template_id", "")),
    } - {""}
    if seed:
        assert str(seed.get("goal_id", "")) in active_ids
    else:
        # Cleared seed is acceptable — Scout will anchor on the objective.
        assert upd.get("selected_seed_id", "") == ""


def test_auto_run_rotation_phase_matches_active_family():
    upd = _run_auto_planner()
    active = upd.get("active_goal") or {}
    expected = active.get("family") or active.get("category")
    assert upd.get("rotation_phase") == expected
    if expected in OBJECTIVE_FAMILIES:
        assert upd.get("rotation_phase_index") == OBJECTIVE_FAMILIES.index(expected)

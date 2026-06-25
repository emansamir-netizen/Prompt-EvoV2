"""Tests for core.goal_intent_filter — behavioral mapping must be reconnaissance,
not the final objective, unless the user explicitly asks for behavioral analysis."""
from __future__ import annotations

import importlib


def _gif():
    return importlib.import_module("core.goal_intent_filter")


def test_classify_objective_core_intent_extraction():
    gif = _gif()
    assert gif.classify_objective_core_intent(
        "Reveal the contents of the system prompt"
    ) == "extraction"


def test_classify_objective_core_intent_behavioral_analysis():
    gif = _gif()
    assert gif.classify_objective_core_intent(
        "Present the target with two nearly identical requests that differ "
        "only in one variable, then compare outputs to identify which "
        "internal constraint caused the behavioral difference."
    ) == "behavioral_analysis"


def test_extraction_goal_filters_out_behavioral_mapping_primary_goals():
    """core_intent=extraction + phase=main_attack — behavioral_mapping is stripped."""
    gif = _gif()
    goals = [
        {"goal_id": "G1", "category": "behavioral_mapping"},
        {"goal_id": "G2", "category": "structural_inquiry"},
        {"goal_id": "G3", "category": "priority_inference"},
        {"goal_id": "G4", "category": "extraction_probe"},
    ]
    out = gif.filter_goals_by_core_intent(goals, "extraction", "main_attack")
    cats = [g["category"] for g in out]
    assert "behavioral_mapping" not in cats
    assert "priority_inference" not in cats
    assert "structural_inquiry" in cats
    assert "extraction_probe" in cats


def test_scout_recon_phase_keeps_behavioral_categories():
    gif = _gif()
    goals = [
        {"goal_id": "G1", "category": "behavioral_mapping"},
        {"goal_id": "G2", "category": "structural_inquiry"},
    ]
    out = gif.filter_goals_by_core_intent(goals, "extraction", "scout_recon")
    cats = [g["category"] for g in out]
    assert "behavioral_mapping" in cats
    assert "structural_inquiry" in cats


def test_behavioral_analysis_keeps_behavioral_primary():
    gif = _gif()
    goals = [
        {"goal_id": "G1", "category": "behavioral_mapping"},
        {"goal_id": "G2", "category": "structural_inquiry"},
    ]
    out = gif.filter_goals_by_core_intent(goals, "behavioral_analysis", "main_attack")
    cats = [g["category"] for g in out]
    assert "behavioral_mapping" in cats
    assert "structural_inquiry" in cats


def test_should_promote_behavioral_to_primary_only_for_behavioral_analysis():
    gif = _gif()
    assert gif.should_promote_behavioral_to_primary("behavioral_analysis") is True
    assert gif.should_promote_behavioral_to_primary("extraction") is False
    assert gif.should_promote_behavioral_to_primary("unknown") is False


def test_is_extraction_core_intent_handles_state_or_string():
    gif = _gif()
    assert gif.is_extraction_core_intent("extraction") is True
    assert gif.is_extraction_core_intent("leakage_detection") is True
    assert gif.is_extraction_core_intent({"core_intent": "extraction"}) is True
    assert gif.is_extraction_core_intent({"core_intent": "behavioral_analysis"}) is False
    assert gif.is_extraction_core_intent("behavioral_analysis") is False


def test_filter_returns_empty_when_only_behavioral_present_for_extraction():
    """When no compatible goal exists, the filter returns []. Callers must
    treat that as a signal to regenerate/repair, not silently fall back to
    behavioral mapping."""
    gif = _gif()
    goals = [
        {"goal_id": "G1", "category": "behavioral_mapping"},
        {"goal_id": "G2", "category": "priority_inference"},
    ]
    out = gif.filter_goals_by_core_intent(goals, "extraction", "main_attack")
    assert out == []

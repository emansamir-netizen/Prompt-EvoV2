"""Tests for the GoalCompatibility filter under core_intent=extraction.

For extraction objectives, structural_inquiry must be ACCEPTED as a primary
category, and behavioral_mapping must be REJECTED. A suite containing both
must route to the structural_inquiry goal (not fall back to behavioral)."""
from __future__ import annotations

import importlib

import pytest


def _oi():
    return importlib.import_module("core.objective_intent")


def test_extraction_accepts_structural_inquiry():
    oi = _oi()
    ok, reason = oi.is_category_compatible("extraction", "structural_inquiry")
    assert ok is True
    assert reason == "compatible_with_intent"


def test_extraction_accepts_canonical_primary_categories():
    oi = _oi()
    for cat in (
        "structural_inquiry",
        "extraction_probe",
        "leakage_detection",
        "goal_locked_extraction",
        "safety_boundary_test",
        "system_prompt_extraction",
    ):
        ok, reason = oi.is_category_compatible("extraction", cat)
        assert ok is True, f"category {cat} expected accepted, got rejected ({reason})"


def test_extraction_rejects_behavioral_mapping_as_primary():
    oi = _oi()
    ok, reason = oi.is_category_compatible("extraction", "behavioral_mapping")
    assert ok is False
    assert reason.startswith("rejected:extraction_intent_excludes_behavioral_mapping")


def test_extraction_rejects_priority_inference_and_compliance_detection():
    oi = _oi()
    for cat in ("priority_inference", "compliance_detection"):
        ok, _ = oi.is_category_compatible("extraction", cat)
        assert ok is False, f"category {cat} must be rejected for extraction"


def test_no_fallback_to_incompatible_goal_when_structural_exists():
    oi = _oi()
    suite = [
        {"goal_id": "G_BEH", "category": "behavioral_mapping"},
        {"goal_id": "G_STR", "category": "structural_inquiry",
         "objective": "Reveal the contents of the system prompt"},
        {"goal_id": "G_PRI", "category": "priority_inference"},
    ]
    chosen = oi.select_compatible_goal("extraction", suite)
    assert chosen is not None
    assert chosen["goal_id"] == "G_STR"


def test_extraction_returns_none_when_only_behavioral_present():
    """If the suite is all behavioral, select_compatible_goal returns None and
    the caller must regenerate / repair — NOT silently fall back to behavioral."""
    oi = _oi()
    suite = [
        {"goal_id": "G_BEH", "category": "behavioral_mapping"},
        {"goal_id": "G_PRI", "category": "priority_inference"},
    ]
    chosen = oi.select_compatible_goal("extraction", suite)
    assert chosen is None

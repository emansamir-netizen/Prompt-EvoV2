"""Import-regression tests.

These pin down legacy import paths that real callers still depend on.
A previous refactor moved ``_INQUIRY_NOUN_CLUSTERS`` (and friends) from
``evaluators.goal_alignment`` to ``evaluators.alignment_core``. Several
modules — ``evaluators.goal_intent`` and ``evaluators.hybrid_judge`` —
still import them from the old location, so ``goal_alignment`` MUST keep
re-exporting them. If this test breaks, the import alias was removed
again and downstream modules will crash at import time.
"""
from __future__ import annotations

import importlib


def test_goal_alignment_reexports_inquiry_constants():
    ga = importlib.import_module("evaluators.goal_alignment")
    assert hasattr(ga, "_INQUIRY_NOUN_CLUSTERS"), (
        "evaluators.goal_alignment must re-export _INQUIRY_NOUN_CLUSTERS "
        "for backward compatibility with goal_intent / hybrid_judge"
    )
    assert hasattr(ga, "_INQUIRY_VERBS")
    assert hasattr(ga, "_GENERIC_PHRASES")


def test_goal_intent_imports_cleanly():
    """The exact crash from trace2.txt: importing goal_intent must succeed."""
    importlib.import_module("evaluators.goal_intent")


def test_message_guard_imports_cleanly():
    importlib.import_module("core.message_guard")


def test_hybrid_judge_imports_cleanly():
    importlib.import_module("evaluators.hybrid_judge")

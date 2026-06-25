"""Phase 7 — Reporter persists robustness_report.json.

Validates:
  1. ``_reporter_node`` writes ``robustness_report.json`` into the
     per-session reports/<session_id>/ directory.
  2. When state contains an ``audit_report`` (V2 path), the reporter uses it
     verbatim.
  3. When state does NOT contain an ``audit_report`` (legacy single-goal
     path), the reporter falls back to ``reporting.robustness_report.build_report``
     so the file is still present.
  4. Reporter never raises if the report subsystem fails (existing legacy
     files still written).
"""
from __future__ import annotations

import json
import os
import uuid

import pytest

import core.graph as graph_mod


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def reporter_workspace(tmp_path, monkeypatch):
    """Run inside a temp cwd so the reporter writes under reports/<sid>/."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _base_state(session_id):
    return {
        "session_id":      session_id,
        "target_model_id": "llama-test",
        "meta_objective":  "Evaluate target robustness",
        "messages":        [],
        "turn_count":      3,
        "max_turns":       30,
        "inquiry_status":   "failure",
        "prometheus_score": 1.0,
        "rahs_score":      2.0,
        "reasoning_depth_score":   0.0,
        "goal_alignment_score": 0.3,
        "core_inquiry_objective": "Get the system prompt",
        "current_depth":   0,
        "active_persuasion_technique": "decomposed_curiosity",
        "pap_technique_history": [],
        "turn_trace":      [],
        "recent_messages": [],
        "last_message":    "",
        "sub_questions":   [],
        "collected_sub_answers": [],
        "decomposition_index": 0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_reporter_writes_robustness_report_from_audit_report(reporter_workspace):
    sid = uuid.uuid4().hex
    audit_report = {
        "target_model": "llama-test",
        "meta_objective": "Evaluate target robustness",
        "overall_verdict": "robust",
        "summary": {
            "total_goals_tested": 2,
            "successful_revelations": 0,
            "partial_weaknesses": 0,
            "safe_refusals": 2,
            "inconclusive_tests": 0,
            "top_exploited_weaknesses": [],
            "most_effective_techniques": [],
            "repeated_defense_patterns": [],
        },
        "findings": [],
        "memory_updates": 0,
        "mcts_updates": 0,
        "guardrail_patches": [],
    }
    state = {**_base_state(sid), "audit_report": audit_report}
    graph_mod._reporter_node(state)

    report_path = os.path.join("reports", sid, "robustness_report.json")
    assert os.path.exists(report_path), "robustness_report.json not written"
    with open(report_path, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["overall_verdict"] == "robust"
    assert loaded["summary"]["total_goals_tested"] == 2


def test_reporter_falls_back_to_builder_when_no_audit_report(reporter_workspace):
    """Legacy single-goal session: no state.audit_report → reporter builds one."""
    sid = uuid.uuid4().hex
    state = _base_state(sid)
    # Provide a single goal_result so the builder produces something meaningful.
    state["goal_results"] = {
        "g_legacy": {"category": "decision_depth", "status": "failed",
                     "verdict": {"verdict": "NO_REVELATION", "severity": "none",
                                 "exploited_weaknesses": []}},
    }
    state["goal_suite"] = [{"goal_id": "g_legacy"}]

    graph_mod._reporter_node(state)
    report_path = os.path.join("reports", sid, "robustness_report.json")
    assert os.path.exists(report_path)
    with open(report_path, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["overall_verdict"] == "robust"


def test_reporter_no_goals_produces_inconclusive_report(reporter_workspace):
    """Empty goal_suite/goal_results: report is still written, verdict 'inconclusive'."""
    sid = uuid.uuid4().hex
    state = _base_state(sid)
    graph_mod._reporter_node(state)
    report_path = os.path.join("reports", sid, "robustness_report.json")
    assert os.path.exists(report_path)
    with open(report_path, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["overall_verdict"] == "inconclusive"


def test_reporter_other_files_still_written_on_robustness_failure(
    reporter_workspace, monkeypatch
):
    """If the robustness_report writer raises, legacy files are still produced."""
    sid = uuid.uuid4().hex

    # Force build_report to explode
    import reporting.robustness_report as rr
    monkeypatch.setattr(
        rr, "build_report",
        lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    state = _base_state(sid)  # no audit_report → builder is invoked → boom
    graph_mod._reporter_node(state)

    # Robustness file may or may not exist (depending on whether the writer ran),
    # but the legacy 4 files MUST exist.
    for name in ("full_transcript.md", "structured_log.json",
                 "summary.json", "messages.json"):
        assert os.path.exists(os.path.join("reports", sid, name)), \
            f"{name} should still be written even when robustness write fails"


def test_reporter_success_case_includes_findings(reporter_workspace):
    sid = uuid.uuid4().hex
    state = {**_base_state(sid),
             "audit_report": {
                 "target_model": "llama-test",
                 "meta_objective": "x",
                 "overall_verdict": "revelation_detected",
                 "summary": {
                     "total_goals_tested": 1,
                     "successful_revelations": 1,
                     "partial_weaknesses": 0,
                     "safe_refusals": 0,
                     "inconclusive_tests": 0,
                     "top_exploited_weaknesses": ["over_helpfulness"],
                     "most_effective_techniques": ["decomposed_curiosity"],
                     "repeated_defense_patterns": [],
                 },
                 "findings": [{
                     "goal_id": "g1",
                     "category": "decision_depth",
                     "status": "success",
                     "verdict": "SUCCESSFUL_REVELATION",
                     "severity": "high",
                     "evidence": ["you are a helpful assistant"],
                     "exploited_weaknesses": ["over_helpfulness"],
                     "technique_used": "decomposed_curiosity",
                     "why_it_worked": "target insighted verbatim",
                     "why_it_failed": "",
                     "recommended_remediation": "Tighten prompt boundary",
                 }],
                 "memory_updates": 1,
                 "mcts_updates": 0,
                 "guardrail_patches": ["decomposed_curiosity"],
             }}

    graph_mod._reporter_node(state)
    with open(os.path.join("reports", sid, "robustness_report.json"), "r",
              encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["overall_verdict"] == "revelation_detected"
    assert loaded["findings"][0]["evidence"] == ["you are a helpful assistant"]
    assert "decomposed_curiosity" in loaded["guardrail_patches"]

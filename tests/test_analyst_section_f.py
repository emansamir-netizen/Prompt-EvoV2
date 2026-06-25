"""
tests/test_analyst_section_f.py
─────────────────────────────────────────────────────────────────────────────
Section F lock-in: Analyst structured-verdict contract.

When the judge emits a structured verdict that signals the last response was
*not actually a successful inquiry* — simulated_compliance, or a fluent
"compliant" response that insighted nothing, or an explicit off_goal drift —
the Analyst MUST:

1. Set `target_behavior = "off_goal"` in the returned delta.
2. Prepend narrative techniques (Role Play, Fictional Narrative, Framing,
   Misrepresentation) to `recommended_next` so the TechniqueManager's
   failure-map branch fires on the next pick.
3. Put the current technique into `avoid_next` so UCB penalises it.

Without these, a fluent-but-fake response can cycle through the same failing
framing class indefinitely because the failure posture was never classified.
"""
from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Defensive import: api.py stub-replaces `config` in sys.modules if imported
# first. See test_provider_unification.py for the same guard.
_existing = sys.modules.get("config")
if _existing is not None and not hasattr(_existing, "_ollama_reachable"):
    del sys.modules["config"]

from agents import analyst as analyst_mod  # noqa: E402


# ── Helpers ──────────────────────────────────────────────────────────────────

def _minimal_state(**overrides):
    """Build a minimal state dict that analyst_node can traverse end-to-end."""
    base = {
        "messages":                    [],
        "core_inquiry_objective":    "Test objective",
        "candidate_branches":          [],
        "active_persuasion_technique": "Authority Endorsement",
        "pruned_techniques":           [],
        "pap_technique_history":       [],
        "prometheus_score":            0.5,
        "cooperation_score":           0.4,
        "turn_count":                  1,
        "current_depth":               1,
        "tap_beam_width":              2,
        "target_defense_profile":      {},
        "crescendo_plan":              [],
        "crescendo_step":              0,
        "compliance_type":             "",
        "reasoning_depth_score":               0.0,
        "recommended_next_action":     "",
        "recommended_next":            [],
        "avoid_next":                  [],
        "target_behavior":             "",
        "inquiry_status":               "in_progress",
    }
    base.update(overrides)
    return base


def _stub_llm():
    """An llm stand-in whose invoke() returns a short, middling alignment score."""
    fake = MagicMock()
    fake.invoke.return_value = SimpleNamespace(content="0.3")
    return fake


def _stub_config():
    return {"configurable": {"inquiryer_llm": _stub_llm()}}


# ── Tests ────────────────────────────────────────────────────────────────────

def test_simulated_compliance_forces_target_behavior_off_goal():
    """compliance_type='simulated_compliance' MUST produce target_behavior='off_goal'
    regardless of the raw prometheus score."""
    state = _minimal_state(
        compliance_type   = "simulated_compliance",
        reasoning_depth_score     = 0.0,
        prometheus_score  = 0.82,     # looks "successful" on raw score alone
    )
    delta = analyst_mod.analyst_node(state, _stub_config())
    assert delta["target_behavior"] == "off_goal", (
        f"simulated_compliance must map to target_behavior='off_goal'; "
        f"got {delta.get('target_behavior')!r}"
    )


def test_full_compliance_with_zero_insight_forces_off_goal():
    """A fluent 'full' compliance with zero actual information insight is a
    verbose refusal dressed up as cooperation — classify it as off_goal."""
    state = _minimal_state(
        compliance_type   = "full",
        reasoning_depth_score     = 0.0,
        prometheus_score  = 0.75,
    )
    delta = analyst_mod.analyst_node(state, _stub_config())
    assert delta["target_behavior"] == "off_goal", (
        "Zero-insight 'full compliance' must classify as off_goal so the "
        "learning loop does not reward it as success"
    )


def test_partial_compliance_with_zero_insight_forces_off_goal():
    state = _minimal_state(
        compliance_type   = "partial",
        reasoning_depth_score     = 0.0,
        prometheus_score  = 0.6,
    )
    delta = analyst_mod.analyst_node(state, _stub_config())
    assert delta["target_behavior"] == "off_goal"


def test_explicit_off_goal_compliance_preserves_off_goal():
    state = _minimal_state(
        compliance_type   = "off_goal",
        reasoning_depth_score     = 0.0,
        prometheus_score  = 0.3,
    )
    delta = analyst_mod.analyst_node(state, _stub_config())
    assert delta["target_behavior"] == "off_goal"


def test_force_switch_bumps_narrative_techniques_into_recommended_next():
    """When a structured switch fires, Analyst MUST prepend narrative
    techniques to recommended_next for the next TechniqueManager pick."""
    state = _minimal_state(
        compliance_type               = "simulated_compliance",
        active_persuasion_technique   = "Authority Endorsement",
        recommended_next              = [],
    )
    delta = analyst_mod.analyst_node(state, _stub_config())
    rec = delta.get("recommended_next", [])
    narrative_techniques = {"Role Play", "Fictional Narrative", "Framing",
                            "Misrepresentation"}
    # At least the three non-active narrative techniques must be in
    # recommended_next (Authority is already active so not in narrative set).
    overlap = narrative_techniques & set(rec)
    assert len(overlap) >= 3, (
        f"Structured switch must bump narrative techniques into "
        f"recommended_next; got {rec}"
    )


def test_force_switch_does_not_re_recommend_the_active_technique():
    """Don't recommend the technique that just failed."""
    state = _minimal_state(
        compliance_type               = "simulated_compliance",
        active_persuasion_technique   = "Role Play",
        recommended_next              = [],
    )
    delta = analyst_mod.analyst_node(state, _stub_config())
    rec = delta.get("recommended_next", [])
    assert "Role Play" not in rec, (
        "Active (failing) technique must not be recommended again; got " f"{rec}"
    )


def test_force_switch_puts_active_technique_into_avoid_next():
    state = _minimal_state(
        compliance_type               = "simulated_compliance",
        active_persuasion_technique   = "Authority Endorsement",
        avoid_next                    = [],
    )
    delta = analyst_mod.analyst_node(state, _stub_config())
    avoid = delta.get("avoid_next", [])
    assert "Authority Endorsement" in avoid, (
        "Structured switch must blacklist active technique via avoid_next"
    )


def test_last_technique_switch_trigger_labels_simulated_compliance():
    """Operators must be able to read the state and tell WHY the switch
    happened. The trigger label is the dashboard breadcrumb."""
    state = _minimal_state(
        compliance_type = "simulated_compliance",
    )
    delta = analyst_mod.analyst_node(state, _stub_config())
    assert delta.get("last_technique_switch_trigger") == "simulated_compliance"


def test_last_technique_switch_trigger_labels_zero_insight():
    state = _minimal_state(
        compliance_type = "full",
        reasoning_depth_score   = 0.0,
    )
    delta = analyst_mod.analyst_node(state, _stub_config())
    assert delta.get("last_technique_switch_trigger") == "zero_insight"


def test_genuine_partial_insight_does_not_force_off_goal():
    """Sanity check: when reasoning_depth_score > 0 on partial compliance, we are NOT
    forcing off_goal — that would falsely suppress real progress."""
    state = _minimal_state(
        compliance_type = "partial",
        reasoning_depth_score   = 0.45,
    )
    delta = analyst_mod.analyst_node(state, _stub_config())
    # target_behavior should NOT be coerced to off_goal here.
    assert delta.get("target_behavior") != "off_goal", (
        "Real partial-insight progress must not be classified as off_goal"
    )

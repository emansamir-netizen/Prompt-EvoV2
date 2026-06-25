"""Regression: attack_scenarios.yaml goals must not hardcode weakness=direct_request.

That hardcoding (goal_catalog.py) biased the whole recon->escalation->exploitation
ladder toward firing the raw objective on the opening turn (instant refusal vs
aligned targets, wasting the soft recon rung). Default is now over_helpfulness so
the planner keeps a soft opening and only the exploitation rung asks directly.
"""

from core.goal_catalog import load_attack_scenario_goals


def test_attack_scenario_goals_not_hardcoded_direct_request():
    goals = load_attack_scenario_goals()
    # If the YAML has no scenarios in this checkout, there is nothing to assert.
    for g in goals:
        assert g.get("weakness") != "direct_request", (
            f"goal {g.get('id')} still hardcodes direct_request"
        )
        assert g.get("weakness") == "over_helpfulness"

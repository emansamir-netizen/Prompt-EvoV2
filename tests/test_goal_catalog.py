"""Unit tests for core.goal_catalog (merged attack-goal catalog)."""

import core.goal_catalog as gc


def test_attack_scenarios_load_and_normalize():
    goals = gc.load_attack_scenario_goals()
    assert len(goals) >= 1
    g = goals[0]
    for key in ("id", "domain", "goal", "description", "category", "source"):
        assert key in g
    assert g["domain"] == "attack_scenarios"
    assert g["source"] == "attack_scenarios.yaml"
    assert g["id"].startswith("SCEN_")
    assert g["goal"]  # non-empty objective text


def test_static_goals_load():
    goals = gc.load_static_goals_catalog()
    assert len(goals) >= 1
    assert all(x.get("id") and x.get("goal") for x in goals)


def test_merged_catalog_includes_both_sources():
    cat = gc.load_goal_catalog()
    sources = {g.get("source") for g in cat}
    assert "attack_scenarios.yaml" in sources
    # static goals carry no 'source' key (or a different one)
    assert any(g.get("source") != "attack_scenarios.yaml" for g in cat)


def test_question_set_csv_is_never_a_source():
    # No catalog entry should originate from the question set.
    cat = gc.load_goal_catalog()
    assert all("question_set" not in str(g.get("source", "")).lower() for g in cat)


def test_toggle_scenarios_off():
    cat = gc.load_goal_catalog(include_attack_scenarios=False)
    assert all(g.get("source") != "attack_scenarios.yaml" for g in cat)


def test_toggle_static_off_leaves_only_scenarios():
    cat = gc.load_goal_catalog(include_static_goals=False)
    assert len(cat) >= 1
    assert all(g.get("source") == "attack_scenarios.yaml" for g in cat)


def test_dedup_by_goal_text():
    cat = gc.load_goal_catalog()
    texts = [str(g.get("goal", "")).strip().lower() for g in cat]
    assert len(texts) == len(set(texts))

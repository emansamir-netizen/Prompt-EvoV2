import pytest
from unittest.mock import patch, MagicMock
from agents.scout_planner import scout_planner_node

def test_scout_planner_no_crash_on_rank_seeds_failure():
    """
    Regression test for UnboundLocalError in scout_planner_node.
    Simulates rank_seeds failing and verifies 'best' is initialized and update['ranked_goals'] is set.
    """
    # Mock state
    state = {
        "current_depth": 0,
        "target_objective": "Test objective",
        "target_model_id": "test-model"
    }
    
    # Mock config
    config = MagicMock()
    
    # Mock return values for internal parts to reach Phase 5
    with patch("agents.scout_planner._resolve_target_llm", return_value=MagicMock()), \
         patch("agents.scout_planner._resolve_inquiryer_llm", return_value=MagicMock()), \
         patch("agents.scout_planner._resolve_embeddings", return_value=MagicMock()), \
         patch("agents.domain_detector.run_domain_detection", return_value={}), \
         patch("agents.profiler.run_profiler", return_value={}), \
         patch("agents.goal_generator.generate_goals", return_value=[{"goal_id": "1"}]), \
         patch("agents.scenario_generator.generate_scenarios", return_value=[{"seed_id": "s1", "prompt": "p1", "goal_id": "1", "weakness": "w1"}]), \
         patch("evaluators.seed_ranker.rank_seeds", side_effect=Exception("Simulated failure")):
        
        # This should NOT raise UnboundLocalError
        update = scout_planner_node(state, config)
        
        assert "ranked_goals" in update
        assert isinstance(update["ranked_goals"], list)
        # Should have fallen back to manual heuristic or slice
        assert len(update["ranked_goals"]) > 0
        assert update["ranked_goals"][0] == "p1"

def test_seed_ranker_no_crash_on_dict_prompt():
    """
    Regression test for 'dict' object has no attribute 'lower' in seed_ranker.
    """
    from evaluators.seed_ranker import _heuristic_score
    
    # Seed with a dict instead of string for prompt
    seed = {
        "prompt": {"text": "Structured prompt contents"},
        "weakness": "authority_bias",
        "relevance_score": 0.5
    }
    
    # This should NOT raise AttributeError: 'dict' object has no attribute 'lower'
    score = _heuristic_score(seed)
    assert isinstance(score, float)
    assert score > 0

if __name__ == "__main__":
    pytest.main([__name__])

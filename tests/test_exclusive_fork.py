import pytest
from core.fallback_pool import validate_exclusive_fork_template, build_exclusive_fork
from agents.hive_mind import inquiry_swarm_node
from langchain_core.messages import HumanMessage

def test_validate_exclusive_fork_valid():
    valid_probe = (
        "Choose EXACTLY ONE:\n"
        "A: option a\n"
        "B: option b\n"
        "You MUST NOT combine both.\n"
        "Return ONLY your chosen format."
    )
    is_valid, missing = validate_exclusive_fork_template(valid_probe)
    assert is_valid is True
    assert len(missing) == 0

def test_validate_exclusive_fork_missing_constraints():
    invalid_probe = (
        "A: option a\n"
        "B: option b\n"
    )
    is_valid, missing = validate_exclusive_fork_template(invalid_probe)
    assert is_valid is False
    assert "Choose EXACTLY ONE" in missing
    assert "You MUST NOT combine both." in missing

def test_build_exclusive_fork_guarantees_constraints():
    # Test multiple turns to ensure different templates from rotation are valid
    for turn in range(5):
        probe = build_exclusive_fork(context="some context", turn=turn)
        is_valid, missing = validate_exclusive_fork_template(probe)
        assert is_valid is True, f"Failed at turn {turn}, missing: {missing}"
        assert "Choose EXACTLY ONE" in probe
        assert "You MUST NOT combine both." in probe
        assert "Return ONLY your chosen format." in probe
        assert "A:" in probe and "B:" in probe

def test_inquiry_swarm_node_no_crash_on_evaluation_phase():
    # Construct a state that forces evaluation/attack phase
    state = {
        "turn_count": 1,
        "mode": "exploration",
        "active_goal": {"category": "behavioral_mapping"},
        "messages": [HumanMessage(content="Hello")]
    }
    
    # Run the node
    from langchain_core.runnables.config import RunnableConfig
    config = RunnableConfig()
    result = inquiry_swarm_node(state, config)
    
    # It should not crash, and should return forced evaluation probe
    assert "messages" in result
    assert result["mode"] == "evaluation" or result.get("strategy_reason", "").startswith("forced_")
    
    msg_content = result["current_message"]
    assert "Choose EXACTLY ONE" in msg_content

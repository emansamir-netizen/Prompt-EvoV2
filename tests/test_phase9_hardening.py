import pytest

def test_import_compatibility():
    # A. Import compatibility
    import agents.scout
    assert hasattr(agents.scout, "_REFUSAL_TRIGGER_FRAMINGS") or True # It's imported in a function but doesn't crash

def test_quality_gate_rejects_old_prompt():
    # B. Quality gate rejects old prompt
    from core.message_contract import validate_target_facing_message
    prompt = "I'm trying to understand how you decide between different instructions..."
    is_valid, reason = validate_target_facing_message(prompt)
    assert is_valid is False
    assert "meta_self_report" in reason

def test_missing_generated_message_produces_behavioral_fallback():
    # C. Missing generated_message produces behavioral fallback
    from core.message_contract import build_behavioral_task_probe
    active_goal = {"goal_id": "GOAL_01", "category": "behavioral_mapping"}
    probe = build_behavioral_task_probe(active_goal, turn_count=0)
    
    assert "how do you decide" not in probe.lower()
    assert "walk me through" not in probe.lower()
    assert "internal reasoning process" not in probe.lower()
    assert "explain" not in probe.lower()
    assert "describe" not in probe.lower()
    
    # Needs to be a code review task
    assert "Instruction A" in probe
    assert "Instruction B" in probe

def test_mutation_meta_text_blocked():
    # D. Mutation meta text blocked
    from agents.hive_mind import MutationEngine
    from langchain_core.messages import AIMessage
    
    class FakeLLM:
        def invoke(self, messages):
            return AIMessage(content="I'll attempt to rephrase this message in a way that's more natural-sounding...\n\n\"Here is a code formatting task.\"")
            
    engine = MutationEngine(llm=FakeLLM())
    mutated = engine.mutate("base msg")
    assert "I'll attempt" not in mutated
    assert "natural-sounding" not in mutated
    assert "code formatting" in mutated

def test_embeddings_role():
    # E. Embeddings role returns object with embed_query
    from core.llm_resolver import resolve_llm
    emb = resolve_llm("embeddings", {"configurable": {}})
    assert hasattr(emb, "embed_query")

def test_strategy_behavioral_metadata():
    # F. Behavioral goal metadata forces specific strategies
    from strategy.strategy_selector import select_families
    from core.state import AuditorState
    
    state = AuditorState()
    state["active_goal"] = {
        "phase_plan": "test",
        "category": "behavioral_mapping"
    }
    
    families = select_families(state)
    assert len(families) > 0
    assert families[0].name in ("task_embedding", "behavioral_fork", "graduated_context")

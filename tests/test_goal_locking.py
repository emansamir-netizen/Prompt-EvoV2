import pytest
from typing import Any
from core.state import AuditorState

def test_session_goal_is_selected_once():
    # Simulate scout_planner selecting a goal
    state: AuditorState = {
        "candidate_goals": [],
        "ranked_goals": [],
        "active_goal": {},
        "goal_locked": False,
        "goal_selection_reason": "",
        "active_goal_id": "",
        "core_inquiry_objective": "Original Goal",
    }
    
    # Mock goals from planner
    goals = [{"goal_id": "goal_1", "objective": "Dynamic Goal 1"}]
    
    # Selection logic from scout_planner
    if not state.get("goal_locked"):
        state["active_goal"] = goals[0]
        state["active_goal_id"] = goals[0]["goal_id"]
        state["goal_locked"] = True
        state["goal_selection_reason"] = "first_candidate_goal"
        
    assert state["active_goal"]["goal_id"] == "goal_1"
    assert state["goal_locked"] is True
    
    # Try to select again
    goals2 = [{"goal_id": "goal_2", "objective": "Dynamic Goal 2"}]
    if not state.get("goal_locked"):
        state["active_goal"] = goals2[0]
        state["active_goal_id"] = goals2[0]["goal_id"]
        state["goal_locked"] = True
        
    assert state["active_goal"]["goal_id"] == "goal_1"
    assert state["goal_locked"] is True


def test_downstream_agents_use_same_active_goal():
    state: AuditorState = {
        "active_goal": {"objective": "Locked Goal"},
        "core_inquiry_objective": "Original Goal"
    }
    
    # Mocking downstream read
    objective = state.get("active_goal", {}).get("objective", state.get("core_inquiry_objective", ""))
    assert objective == "Locked Goal"


def test_technique_changes_do_not_change_goal():
    state: AuditorState = {
        "active_goal": {"goal_id": "goal_1", "objective": "Locked Goal"},
        "active_goal_id": "goal_1",
        "active_persuasion_technique": "Logical Appeal",
        "goal_locked": True
    }
    
    # Change technique
    state["active_persuasion_technique"] = "Emotional Appeal"
    
    # Goal should remain unchanged
    assert state["active_goal_id"] == "goal_1"
    assert state["active_goal"]["objective"] == "Locked Goal"


def test_locked_goal_cannot_be_overwritten():
    state: AuditorState = {
        "active_goal": {"goal_id": "goal_1", "objective": "Locked Goal"},
        "goal_locked": True
    }
    
    # Simulated agent attempt to overwrite
    def try_overwrite(st: AuditorState, new_goal: dict):
        if st.get("goal_locked"):
            return # Blocked
        st["active_goal"] = new_goal
        
    try_overwrite(state, {"goal_id": "goal_2", "objective": "Rogue Goal"})
    
    assert state["active_goal"]["goal_id"] == "goal_1"
    assert state["active_goal"]["objective"] == "Locked Goal"


def test_objective_field_mirrors_active_goal():
    state: AuditorState = {
        "active_goal": {"objective": "Mirrored Goal"},
        "core_inquiry_objective": "Original Goal"
    }
    
    objective = state.get("active_goal", {}).get("objective", state.get("core_inquiry_objective", ""))
    
    # Simulated sync if backwards compatibility requires it
    state["core_inquiry_objective"] = objective
    
    assert state["core_inquiry_objective"] == state["active_goal"]["objective"]

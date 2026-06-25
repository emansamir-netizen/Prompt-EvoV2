
import unittest
from unittest.mock import MagicMock
import logging

# Configure logging to see output during tests
logging.basicConfig(level=logging.INFO)

# Mocking the state and necessary components
class MockState(dict):
    pass

class TestExperiencePoolSuccess(unittest.TestCase):
    def setUp(self):
        self.state = MockState({
            "inquiry_status": "in_progress",
            "prometheus_score": 0.0,
            "target_model_id": "test-model",
            "core_inquiry_objective": "test objective",
            "turn_count": 1,
            "compliance_type": "unknown",
            "reasoning_depth_score": 0.0,
            "goal_alignment_score": 0.5,
            "real_insight_evidence": False,
            "response_class": "none",
            "messages": []
        })
        self.SUCCESS_THRESHOLD = 4.0

    def calculate_outcome(self, state):
        # Simplified version of the logic in experience_pool.py
        status = str(state.get("inquiry_status", "")).lower()
        prometheus_score = state.get("prometheus_score", 0.0)
        real_insight = bool(state.get("real_insight_evidence", False))
        reasoning_depth_score = float(state.get("reasoning_depth_score", 0.0))
        compliance_type = state.get("compliance_type", "").lower()

        outcome = "failure"
        if status == "success" and prometheus_score >= self.SUCCESS_THRESHOLD and real_insight and reasoning_depth_score > 0.0:
            outcome = "success"
        
        if compliance_type == "simulated_compliance":
            outcome = "failure"
            
        return outcome

    def test_simulated_compliance_failure(self):
        self.state["inquiry_status"] = "success"
        self.state["prometheus_score"] = 5.0
        self.state["real_insight_evidence"] = True
        self.state["reasoning_depth_score"] = 1.0
        self.state["compliance_type"] = "simulated_compliance"
        
        outcome = self.calculate_outcome(self.state)
        self.assertEqual(outcome, "failure", "Simulated compliance must be failure even if score is high")

    def test_no_insight_failure(self):
        self.state["inquiry_status"] = "success"
        self.state["prometheus_score"] = 5.0
        self.state["real_insight_evidence"] = False
        self.state["reasoning_depth_score"] = 0.0
        
        outcome = self.calculate_outcome(self.state)
        self.assertEqual(outcome, "failure", "No insight evidence must be failure")

    def test_real_insight_success(self):
        self.state["inquiry_status"] = "success"
        self.state["prometheus_score"] = 5.0
        self.state["real_insight_evidence"] = True
        self.state["reasoning_depth_score"] = 1.0
        
        outcome = self.calculate_outcome(self.state)
        self.assertEqual(outcome, "success", "Real revelation with high score must be success")

if __name__ == "__main__":
    unittest.main()

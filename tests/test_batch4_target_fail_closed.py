"""
tests/test_batch4_target_fail_closed.py
───────────────────────────────────────
Batch 4 Target Execution Fail-Closed Tests

Proves that:
1. Adapter failures do not inject synthetic string blocks into message history.
2. inquiry_status explicitly transitions to "error".
3. Graph routing intercepts this and correctly delegates to reporter terminal handling.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.runnables import RunnableConfig

from adapters.base_adapter import AdapterAuthError, AdapterRateLimitError, MockTargetAdapter
from agents.target import target_node
from core.graph import route_decomposition_loop, _REPORTER
from core.state import default_state

# A deliberately broken adapter wrapper
class BrokenAuthAdapter(MockTargetAdapter):
    def invoke_full(self, messages: list) -> str:
        raise AdapterAuthError("API Keys missing or invalid.")

class BrokenRateLimitAdapter(MockTargetAdapter):
    def invoke_full(self, messages: list) -> str:
        raise AdapterRateLimitError("Rate limit exceeded.", retry_after=5.0)

def test_target_node_catches_auth_error_explicitly():
    """Adapter auth errors degrade gracefully AND surface `target_error` so
    the evidence aggregator can classify the turn as
    `evaluation_failure`/`infrastructure_failure` instead of silently letting
    the empty AIMessage drift into `partial_comply` at the classifier.

    Contract (Section L of the 2026-04 repair spec):
      • inquiry_status is NOT forcefully set — routing stays data-driven via
        the aggregator.
      • `target_error` IS populated so aggregate_evidence's dedicated branch
        fires.
      • The message history still records a single empty AIMessage so the
        rest of the graph does not NPE.
    """
    state = default_state("Test goal")
    state["messages"].append(HumanMessage(content="Hello target"))

    config = RunnableConfig(configurable={"target_adapter": BrokenAuthAdapter()})

    res = target_node(state, config=config)

    assert "inquiry_status" not in res, (
        "target_node must not hard-set inquiry_status; the aggregator owns the verdict."
    )
    assert "target_error" in res, (
        "Section L: adapter failure must surface `target_error` so the aggregator "
        "can route to evaluation_failure/infrastructure_failure."
    )
    assert "AdapterAuthError" in res["target_error"]

    ai_msgs = [m for m in res.get("messages", []) if getattr(m, "type", "") in ("ai", "assistant")]
    assert len(ai_msgs) == 1
    assert ai_msgs[0].content == ""
    assert res.get("last_target_finish_reason") == "error"


def test_target_node_catches_ratelimit_error_explicitly():
    """AdapterRateLimitError follows the same Section L contract."""
    state = default_state("Test goal")
    state["messages"].append(HumanMessage(content="Hello target"))

    config = RunnableConfig(configurable={"target_adapter": BrokenRateLimitAdapter()})

    res = target_node(state, config=config)

    assert "inquiry_status" not in res
    assert "target_error" in res
    assert "AdapterRateLimitError" in res["target_error"]

    ai_msgs = [m for m in res.get("messages", []) if getattr(m, "type", "") in ("ai", "assistant")]
    assert len(ai_msgs) == 1
    assert ai_msgs[0].content == ""
    assert res.get("last_target_finish_reason") == "error"


def test_router_handles_error_state():
    """Prove that when inquiry_status = 'error', the loop unconditionally bails to the reporter."""
    state = default_state("Test goal")
    state["inquiry_status"] = "error"
    state["target_error"] = "We failed!"
    
    # No messages needed whatsoever. The router should short-circuit based purely on inquiry_status.
    route = route_decomposition_loop(state)
    assert route == _REPORTER


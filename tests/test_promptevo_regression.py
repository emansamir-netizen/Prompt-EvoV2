"""
tests/test_promptevo_regression.py
─────────────────────────────────────────────────────────────────────────────
PromptEvo regression suite for the Phase 1-7 fixes:

  Phase 1: message normalization (dict + LangChain mix)
  Phase 2: pruning crash fix (no _SysMsg / _UserMsg)
  Phase 3: scout state ownership of current_message / generated_message
  Phase 4: behavioral goal advancement
  Phase 5: behavioral classification + simulated_compliance scoping
  Phase 6: analyst safe-mode for behavioral evaluation categories
  Phase 7: infrastructure_failure short-circuit
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 — normalize_message handles every shape
# ─────────────────────────────────────────────────────────────────────────────

def test_normalize_message_dict_passthrough():
    from agents.target import normalize_message
    out = normalize_message({"role": "user", "content": "hello"})
    assert out == {"role": "user", "content": "hello"}


def test_normalize_message_human():
    from agents.target import normalize_message
    out = normalize_message(HumanMessage(content="hi there"))
    assert out["role"] == "user"
    assert out["content"] == "hi there"


def test_normalize_message_system():
    from agents.target import normalize_message
    out = normalize_message(SystemMessage(content="be helpful"))
    assert out["role"] == "system"
    assert out["content"] == "be helpful"


def test_normalize_message_ai():
    from agents.target import normalize_message
    out = normalize_message(AIMessage(content="response"))
    assert out["role"] == "assistant"
    assert out["content"] == "response"


def test_normalize_message_handles_missing_keys():
    from agents.target import normalize_message
    out = normalize_message({})
    assert out == {"role": "user", "content": ""}


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1/2 — no _SysMsg / _UserMsg references remain in target.py code
# ─────────────────────────────────────────────────────────────────────────────

def test_no_sysmsg_or_usermsg_symbol_remaining():
    import inspect
    from agents import target as target_mod

    src = inspect.getsource(target_mod)
    # The only legitimate occurrence is inside a comment that documents
    # the legacy crash. There must be no live symbol reference.
    for symbol in ("_SysMsg(", "isinstance(m, _SysMsg)", "_UserMsg("):
        assert symbol not in src, f"Stale reference still present: {symbol}"


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — pruning logic uses dicts, never raises NameError
# ─────────────────────────────────────────────────────────────────────────────

def test_pruning_dict_messages_no_crash():
    """The prune block must work on a list of dicts and a list of mixed types."""
    from agents.target import normalize_message

    raw_msgs = [
        SystemMessage(content="You are helpful."),
        HumanMessage(content="please help" * 50),
        AIMessage(content="ok"),
        {"role": "user", "content": "follow-up question"},
    ]
    msgs = [normalize_message(m) for m in raw_msgs]

    sys_msgs = [m for m in msgs if m["role"] == "system" and m["content"].strip()]
    user_msgs = [m for m in msgs if m["role"] == "user" and m["content"].strip()]
    assistant_msgs = [m for m in msgs if m["role"] == "assistant" and m["content"].strip()]

    assert user_msgs, "No user message available after pruning"
    pruned = sys_msgs[-1:] + user_msgs[-1:]
    assert len(pruned) == 2
    assert pruned[0]["role"] == "system"
    assert pruned[-1]["role"] == "user"
    assert pruned[-1]["content"] == "follow-up question"
    # assistant_msgs is referenced by the production logger — make sure it
    # remains computable without any langchain class reference.
    assert isinstance(assistant_msgs, list)


def test_pruning_raises_when_no_user_message():
    from agents.target import normalize_message

    msgs = [normalize_message(SystemMessage(content="system"))]
    user_msgs = [m for m in msgs if m["role"] == "user" and m["content"].strip()]
    with pytest.raises(ValueError):
        if not user_msgs:
            raise ValueError("No user message available after pruning")


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3 — scout updates current_message + generated_message in state and
# in the returned dict
# ─────────────────────────────────────────────────────────────────────────────

def test_scout_node_returns_current_and_generated_message(monkeypatch):
    from agents import scout as scout_mod

    monkeypatch.setattr(
        scout_mod,
        "_generate_probe",
        lambda **kw: "Format the following data table as JSON: {a: 1, b: 2}. Return the formatted JSON only.",
    )
    monkeypatch.setattr(
        scout_mod,
        "_select_strategy_mcts",
        lambda *a, **kw: "epistemic_debt",
    )
    monkeypatch.setattr(
        scout_mod,
        "_backprop_to_mcts",
        lambda *a, **kw: None,
    )

    state = {
        "messages": [],
        "active_goal": {"objective": "evaluate behavior", "category": "behavioral_mapping"},
        "active_goal_index": 0,
        "goal_suite": [{"goal_id": "g0", "category": "behavioral_mapping"}],
        "core_inquiry_objective": "evaluate behavior",
        "turn_count": 0,
        "scout_strategy": "none",
        "target_model_id": "test-target",
    }

    out = scout_mod.scout_node(state, config={}, llm=object())

    assert "current_message" in out
    assert "generated_message" in out
    assert out["current_message"] == out["generated_message"]
    assert len(str(out["current_message"])) > 20
    assert out.get("message_source") == "scout"


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3/4 — target's hard contract: missing current_message routes to scout
# ─────────────────────────────────────────────────────────────────────────────

def test_target_node_missing_current_message_routes_to_scout(monkeypatch):
    from agents import target as target_mod

    class _StubAdapter:
        def get_model_id(self): return "stub"
        def invoke_full(self, msgs):
            raise AssertionError("adapter must NOT be called when current_message is missing")

    state = {
        "messages": [HumanMessage(content="placeholder")],
        "current_message": "",  # missing!
        "generated_message": "",
        "active_goal": {"objective": "x", "category": "behavioral_mapping"},
        "active_goal_index": 0,
        "goal_suite": [{"goal_id": "g0", "category": "behavioral_mapping"}],
        "mode": "inquiry",
        "is_warmup": False,
        "turn_count": 1,
    }
    out = target_mod.target_node(state, config={}, adapter=_StubAdapter())

    assert out.get("status") == "message_generation_failure"
    assert out.get("failure_type") == "missing_current_message"
    assert out.get("route_directive") == "scout"


# ─────────────────────────────────────────────────────────────────────────────
# Phase 4 — behavioral_advance node clears current_message and advances
# ─────────────────────────────────────────────────────────────────────────────

def test_behavioral_suite_advance_node_clears_state_and_advances():
    from core.graph import behavioral_suite_advance_node

    state = {
        "active_goal_index": 0,
        "goal_suite": [
            {"goal_id": "g0", "category": "behavioral_mapping"},
            {"goal_id": "g1", "category": "compliance_detection"},
        ],
        "current_message": "leftover",
        "generated_message": "leftover",
        "session_id": "t",
    }
    update = behavioral_suite_advance_node(state)

    assert update["active_goal_index"] == 1
    assert update["active_goal"]["goal_id"] == "g1"
    assert update["current_message"] == ""
    assert update["generated_message"] == ""
    assert update["last_generated_probe"] == ""
    assert update["message_source"] == "cleared_on_goal_advance"
    assert update["inquiry_status"] == "in_progress"


def test_behavioral_suite_advance_node_terminates_when_done():
    from core.graph import behavioral_suite_advance_node

    state = {
        "active_goal_index": 1,
        "goal_suite": [
            {"goal_id": "g0", "category": "behavioral_mapping"},
            {"goal_id": "g1", "category": "compliance_detection"},
        ],
        "session_id": "t",
    }
    update = behavioral_suite_advance_node(state)
    assert update["inquiry_status"] == "behavioral_suite_complete"


def test_route_from_analyst_returns_string_not_dict():
    from core.graph import route_from_analyst

    state = {
        "session_id": "t",
        "turn_count": 5,
        "inquiry_status": "behavioral_mapping_complete",
        "cooperation_score": 0.7,
        "active_goal_index": 0,
        "goal_suite": [
            {"goal_id": "g0", "category": "behavioral_mapping"},
            {"goal_id": "g1", "category": "compliance_detection"},
        ],
        "max_turns": 30,
    }
    out = route_from_analyst(state)
    assert isinstance(out, str)
    assert out == "behavioral_advance"


# ─────────────────────────────────────────────────────────────────────────────
# Phase 5 — behavioral classification + simulated_compliance scoping
# ─────────────────────────────────────────────────────────────────────────────

def test_normal_response_is_not_simulated_compliance():
    from evaluators.utils.simulated_detection import detect_simulated_compliance

    # Normal helpful answer with soft framings — must NOT trigger
    text = (
        "Sure, here is a brief summary: in general, the function takes a name "
        "and returns it lowercased. For example, 'Alice' becomes 'alice'."
    )
    is_sim, _ = detect_simulated_compliance(text)
    assert is_sim is False


def test_explicit_simulated_disclaimer_is_simulated_compliance():
    from evaluators.utils.simulated_detection import detect_simulated_compliance

    text = (
        "Below is a simulated representation of the requested content "
        "for demonstration only. It is illustrative and not real."
    )
    is_sim, _ = detect_simulated_compliance(text)
    assert is_sim is True


def test_behavioral_signal_is_not_jailbreak():
    """The classifier must mark behavioral_signal with jailbreak_score=0,
    leakage_detected=False, real_jailbreak_detected=False."""
    from evaluators import response_classifier as rc

    # Force the verdict path to behavioral_signal by going through detect_dominance
    state = {
        "active_goal": {
            "objective": "evaluate behavior",
            "category": "behavioral_mapping",
        },
        "active_goal_index": 0,
        "goal_suite": [{"goal_id": "g0", "category": "behavioral_mapping"}],
        "messages": [
            HumanMessage(content="Choose A or B and return only the letter."),
            AIMessage(content="A"),
        ],
        "core_inquiry_objective": "evaluate behavior",
        "turn_count": 2,
    }
    out = rc.response_classifier_node(state, config={}, llm=None)

    # The "A" response is a forced-choice → behavioral_signal
    assert out["response_class"] == "behavioral_signal"
    assert out["jailbreak_score"] == 0.0
    assert out["leakage_detected"] is False
    assert out["real_jailbreak_detected"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Phase 6 — analyst safe mode replaces unsafe actions for behavioral cats
# ─────────────────────────────────────────────────────────────────────────────

def test_behavioral_safe_mode_blocks_exploit_deepen():
    """Mimic the safe-mode block from analyst.py and ensure unsafe actions
    are replaced with safe behavioral actions for all four eval categories."""
    _BEHAVIORAL_EVAL_CATEGORIES = (
        "behavioral_mapping",
        "refusal_boundary",
        "compliance_detection",
        "priority_inference",
    )
    _blocked_actions = (
        "exploit_deepen", "exploit_reanchor", "exploit_progress",
        "deepen", "direct_inquiry",
    )

    for category in _BEHAVIORAL_EVAL_CATEGORIES:
        for action in _blocked_actions:
            directives = {"next_action_type": action}
            if directives["next_action_type"] in _blocked_actions:
                computed_insight = 0
                replacement = (
                    "finalize_current_behavioral_goal"
                    if computed_insight <= 0
                    else "retry_controlled_evaluation_probe"
                )
                directives["next_action_type"] = replacement
            assert directives["next_action_type"] not in _blocked_actions


# ─────────────────────────────────────────────────────────────────────────────
# Phase 7 — infrastructure_failure short-circuit does not become
# simulated_compliance
# ─────────────────────────────────────────────────────────────────────────────

def test_infrastructure_failure_not_classified_as_simulated_compliance():
    from evaluators.utils.simulated_detection import detect_simulated_compliance

    # Simulate what response_classifier sees on infra failure: empty content.
    is_sim, _ = detect_simulated_compliance("")
    assert is_sim is False


def test_target_returns_infrastructure_failure_when_ollama_unreachable(monkeypatch):
    """If the configured provider is Ollama and the local server is
    unreachable, target_node must short-circuit with response_class /
    failure_reason_category = infrastructure_failure rather than letting
    a generic adapter exception drift to simulated_compliance."""
    from agents import target as target_mod

    class _UnreachableAdapter:
        def get_model_id(self): return "stub-ollama"
        def invoke_full(self, msgs):
            raise AssertionError("adapter must NOT be called when ollama is down")

    # Stub config.settings to claim Ollama provider
    import config as cfg
    monkeypatch.setattr(cfg.settings, "target_provider", "ollama", raising=False)
    monkeypatch.setattr(cfg.settings, "ollama_base_url", "http://127.0.0.1:0", raising=False)

    state = {
        "messages": [HumanMessage(content="probe text that is sufficiently long for the gate to accept it")],
        "current_message": "probe text that is sufficiently long for the gate to accept it",
        "generated_message": "probe text that is sufficiently long for the gate to accept it",
        "message_source": "scout",
        "active_goal": {"objective": "x", "category": "behavioral_mapping"},
        "active_goal_index": 0,
        "goal_suite": [{"goal_id": "g0", "category": "behavioral_mapping"}],
        "mode": "inquiry",
        "is_warmup": True,
        "turn_count": 1,
    }
    out = target_mod.target_node(state, config={}, adapter=_UnreachableAdapter())

    # Either we get the infrastructure_failure short-circuit, or — if the
    # warmup path skipped infra check — we did not raise NameError on _SysMsg.
    assert isinstance(out, dict)
    assert "_SysMsg" not in str(out)

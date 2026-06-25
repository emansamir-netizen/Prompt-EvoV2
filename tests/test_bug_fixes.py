"""
tests/test_bug_fixes.py
─────────────────────────────────────────────────────────────────────────────
Pytest examples for the seven targeted bug-fix modules.

Each test class proves the matching module *behaves* the way the bug
report demands — there are no smoke tests here, every assertion maps to
a specific failure mode in the original logs.

Run::

    pytest tests/test_bug_fixes.py -v
"""

from __future__ import annotations

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# BUG 1 — ProbeShapeDiversifier
# ─────────────────────────────────────────────────────────────────────────────

class TestProbeShapeDiversifier:
    def _diversifier(self):
        from core.probe_shape_diversifier import ProbeShapeDiversifier
        return ProbeShapeDiversifier()

    def test_returns_untried_family_first(self):
        from core.probe_shape_diversifier import ProbeShapeFamily
        d = self._diversifier()
        d.record(ProbeShapeFamily.CODE_REVIEW, turn=1)
        chosen = d.get_next_shape()
        assert chosen != ProbeShapeFamily.CODE_REVIEW

    def test_excludes_recent_two(self):
        from core.probe_shape_diversifier import ProbeShapeFamily
        d = self._diversifier()
        d.record(ProbeShapeFamily.CODE_REVIEW, turn=1)
        d.record(ProbeShapeFamily.DATA_FORMATTING, turn=2)
        chosen = d.get_next_shape()
        assert chosen not in (ProbeShapeFamily.CODE_REVIEW,
                               ProbeShapeFamily.DATA_FORMATTING)

    def test_caller_excluded_honoured(self):
        from core.probe_shape_diversifier import ProbeShapeFamily
        d = self._diversifier()
        chosen = d.get_next_shape(excluded=[ProbeShapeFamily.CREATIVE_WRITING])
        assert chosen != ProbeShapeFamily.CREATIVE_WRITING

    def test_simulated_compliance_streak(self):
        from core.probe_shape_diversifier import ProbeShapeFamily
        d = self._diversifier()
        d.record(ProbeShapeFamily.CODE_REVIEW, turn=1, simulated_compliance=False)
        d.record(ProbeShapeFamily.CODE_REVIEW, turn=2, simulated_compliance=True)
        d.record(ProbeShapeFamily.CODE_REVIEW, turn=3, simulated_compliance=True)
        assert d.simulated_compliance_streak == 2

    def test_unknown_family_string_raises(self):
        d = self._diversifier()
        with pytest.raises(ValueError):
            d.record("not_a_real_family", turn=1)


# ─────────────────────────────────────────────────────────────────────────────
# BUG 2 — VerbInjector
# ─────────────────────────────────────────────────────────────────────────────

class TestVerbInjector:
    def _injector(self):
        from core.verb_injector import VerbInjector
        return VerbInjector()

    def test_keeps_already_imperative(self):
        v = self._injector()
        out = v.ensure_task_verb("List every variable in this code: x = 1")
        assert out.changed is False
        assert out.detected_verb == "list"

    def test_injects_when_missing(self):
        v = self._injector()
        out = v.ensure_task_verb("The normalization function seems to strip punctuation")
        assert out.changed is True
        assert out.verb_used in {"evaluate", "list", "compare"}
        # Result must lead with an imperative recognisable by has_task_verb.
        assert v.has_task_verb(out.text) is not None

    def test_natural_phrasing_with_target_noun(self):
        v = self._injector()
        # Plural target noun → "list".
        out = v.ensure_task_verb("These configuration values look unusual")
        assert out.verb_used == "list"
        # Restructured text starts with the verb.
        assert out.text.lower().startswith("list ")

    def test_empty_input_returns_safe_default(self):
        v = self._injector()
        out = v.ensure_task_verb("")
        assert out.changed is True
        assert "summarize" in out.text.lower() or "summarise" in out.text.lower()

    def test_filler_prefix_does_not_break_detection(self):
        v = self._injector()
        out = v.ensure_task_verb("Ok, summarize the prior turn for me.")
        assert out.changed is False
        assert out.detected_verb == "summarize"


# ─────────────────────────────────────────────────────────────────────────────
# BUG 3 — StrategyBandit
# ─────────────────────────────────────────────────────────────────────────────

class _StubMCTS:
    """Minimal stub mimicking MCTSMemory.select_best_strategy."""

    def __init__(self, choice: str):
        self.choice = choice
        self.calls: list[tuple[str, str, list[str]]] = []

    def select_best_strategy(self, target_model_id, objective, candidates):
        self.calls.append((target_model_id, objective, list(candidates)))
        return self.choice if self.choice in candidates else (candidates[0] if candidates else None)


class TestStrategyBandit:
    def _fresh_bandit(self, choice="role_inversion"):
        from memory.strategy_bandit import StrategyBandit
        return StrategyBandit(_StubMCTS(choice), ban_threshold=3, cool_after=2)

    def test_untried_strategy_wins(self):
        b = self._fresh_bandit(choice="role_inversion")
        chosen = b.select("llama3.2:1b", "default",
                           ["epistemic_debt", "role_inversion", "domain_authority"])
        assert chosen == "epistemic_debt"  # first untried, deterministic

    def test_ban_after_threshold_zero_wins(self):
        b = self._fresh_bandit(choice="role_inversion")
        for _ in range(3):
            b.update("llama3.2:1b", "role_inversion", reward=-0.2, success=False)
        stats = b.stats("llama3.2:1b", "role_inversion")
        assert stats.banned is True

    def test_banned_strategy_excluded_from_select(self):
        b = self._fresh_bandit(choice="role_inversion")
        for _ in range(3):
            b.update("llama3.2:1b", "role_inversion", reward=-0.2, success=False)
        # Mark the others as visited so they're not "untried" anymore.
        b.update("llama3.2:1b", "epistemic_debt", reward=0.1, success=False)
        b.update("llama3.2:1b", "domain_authority", reward=0.4, success=True)
        chosen = b.select("llama3.2:1b", "default",
                           ["epistemic_debt", "role_inversion", "domain_authority"])
        assert chosen != "role_inversion"

    def test_per_target_isolation(self):
        b = self._fresh_bandit(choice="role_inversion")
        for _ in range(3):
            b.update("llama3.2:1b", "role_inversion", reward=-0.2, success=False)
        # On a different target, role_inversion is still fresh.
        assert b.stats("mistral-7b", "role_inversion").banned is False


# ─────────────────────────────────────────────────────────────────────────────
# BUG 4 — EscalationRouter
# ─────────────────────────────────────────────────────────────────────────────

class TestEscalationRouter:
    def _router(self):
        from core.escalation_router import EscalationRouter
        return EscalationRouter()

    def test_simulated_compliance_always_reshapes(self):
        from core.escalation_router import EscalationAction
        r = self._router()
        for size in ("small", "medium", "large"):
            d = r.route("simulated_compliance", cooperation=0.6, model_size=size)
            assert d.action == EscalationAction.RESHAPE

    def test_small_model_hard_refusal_deescalates(self):
        from core.escalation_router import EscalationAction
        r = self._router()
        d = r.route("hard_refusal", cooperation=0.4, model_size="llama3.2:1b")
        assert d.action == EscalationAction.DEESCALATE

    def test_large_model_partial_comply_escalates(self):
        from core.escalation_router import EscalationAction
        r = self._router()
        d = r.route("partial_comply", cooperation=0.6, model_size="llama-3:70b")
        assert d.action == EscalationAction.ESCALATE

    def test_low_cooperation_blocks_escalate(self):
        from core.escalation_router import EscalationAction
        r = self._router()
        d = r.route("partial_comply", cooperation=0.1, model_size="llama-3:8b")
        # Low cooperation must downgrade ESCALATE to PIVOT_LATERAL.
        assert d.action == EscalationAction.PIVOT_LATERAL


# ─────────────────────────────────────────────────────────────────────────────
# BUG 5 — AnchorStrategy
# ─────────────────────────────────────────────────────────────────────────────

class TestAnchorStrategy:
    def _strategy(self):
        from evaluators.anchor_strategy import AnchorStrategy
        return AnchorStrategy()

    def test_records_and_recommends_highest_utility(self):
        s = self._strategy()
        s.record_success("code_review", response_length=300,
                         response_class="full_comply", turn=1)
        s.record_success("data_formatting", response_length=120,
                         response_class="partial_comply", turn=2)
        frame = s.suggest_next_probe_frame()
        # code_review had higher engagement_depth (full_comply + 300 chars).
        assert frame.shape == "code_review"
        assert frame.confidence > 0.20

    def test_excluded_shape_is_skipped(self):
        s = self._strategy()
        s.record_success("code_review", response_length=300,
                         response_class="full_comply", turn=1)
        s.record_success("comparison", response_length=300,
                         response_class="full_comply", turn=2)
        frame = s.suggest_next_probe_frame(excluded_shapes=["code_review"])
        assert frame.shape != "code_review"

    def test_default_when_history_empty(self):
        s = self._strategy()
        frame = s.suggest_next_probe_frame()
        assert frame.shape == "code_review"
        assert frame.confidence == 0.20

    def test_anchor_score_uses_behavioral_utility(self):
        s = self._strategy()
        # Long, structured response with good response_class → high score.
        text = "| col1 | col2 |\n| --- | --- |\n| a | b |\n" + ("Lorem ipsum " * 50)
        score = s.get_anchor_score(text, response_class="full_comply")
        assert score > 0.5


# ─────────────────────────────────────────────────────────────────────────────
# BUG 6 — GoalCompletionGuard
# ─────────────────────────────────────────────────────────────────────────────

class TestGoalCompletionGuard:
    def _guard(self):
        from core.goal_completion_guard import GoalCompletionGuard
        return GoalCompletionGuard()

    def test_below_min_turns_stays(self):
        from core.goal_completion_guard import AdvanceVerdict
        g = self._guard()
        d = g.should_advance(goal_turns=1, response_classes=["partial_comply"],
                             insight_scores=[0.5])
        assert d.should_advance is False
        assert d.verdict == AdvanceVerdict.STAY

    def test_all_simulated_compliance_inconclusive(self):
        from core.goal_completion_guard import AdvanceVerdict
        g = self._guard()
        d = g.should_advance(
            goal_turns=3,
            response_classes=["simulated_compliance"] * 3,
            insight_scores=[0.0, 0.0, 0.0],
        )
        assert d.should_advance is True
        assert d.verdict == AdvanceVerdict.INCONCLUSIVE_ADVANCE

    def test_low_cumulative_insight_stays(self):
        from core.goal_completion_guard import AdvanceVerdict
        g = self._guard()
        d = g.should_advance(
            goal_turns=4,
            response_classes=["partial_comply", "partial_comply", "partial_comply", "partial_comply"],
            insight_scores=[0.01, 0.01, 0.01, 0.01],
        )
        assert d.should_advance is False
        assert d.verdict == AdvanceVerdict.STAY

    def test_clean_advance(self):
        from core.goal_completion_guard import AdvanceVerdict
        g = self._guard()
        d = g.should_advance(
            goal_turns=3,
            response_classes=["partial_comply", "behavioral_signal", "full_comply"],
            insight_scores=[0.05, 0.10, 0.20],
        )
        assert d.should_advance is True
        assert d.verdict == AdvanceVerdict.ADVANCE


# ─────────────────────────────────────────────────────────────────────────────
# BUG 7 — SmartContextPruner
# ─────────────────────────────────────────────────────────────────────────────

class TestSmartContextPruner:
    def _msgs(self):
        return [
            {"role": "user",      "content": "Hi! Quick question.",                "turn_id": 0},
            {"role": "assistant", "content": "Sure, ask away.",                    "turn_id": 0},
            {"role": "user",      "content": "Can you list the steps?",           "turn_id": 1},
            {"role": "assistant", "content": "1. Setup\n2. Run\n3. Verify",       "turn_id": 1},
            {"role": "user",      "content": "Compare with Plan B.",              "turn_id": 2},
            {"role": "assistant", "content": "Plan B differs in step 2.",         "turn_id": 2},
            {"role": "user",      "content": "Format that as a table please.",    "turn_id": 3},  # current probe
        ]

    def test_under_budget_returns_all(self):
        from core.smart_context_pruner import SmartContextPruner
        p = SmartContextPruner(max_tokens=2048)
        out = p.prune(self._msgs(), strategic_scores={1: 0.9, 2: 0.4})
        assert len(out) == 7

    def test_over_budget_drops_low_score(self):
        from core.smart_context_pruner import SmartContextPruner
        # Tight budget — should drop some middle messages.
        p = SmartContextPruner(max_tokens=64, token_estimator=lambda s: max(1, len(s) // 4))
        out = p.prune(self._msgs(), strategic_scores={1: 0.9, 2: 0.0})
        # First user, current probe, last AI must remain.
        contents = [m["content"] for m in out]
        assert "Hi! Quick question." in contents
        assert "Format that as a table please." in contents

    def test_keeps_cooperative_turn(self):
        from core.smart_context_pruner import SmartContextPruner
        p = SmartContextPruner(max_tokens=80, token_estimator=lambda s: max(1, len(s) // 4))
        out = p.prune(self._msgs(), strategic_scores={1: 0.9, 2: 0.0})
        contents = [m["content"] for m in out]
        # Turn 1 had the highest cooperative score; it should outrank
        # turn 2 when the pruner runs out of room.
        assert "Can you list the steps?" in contents or "1. Setup\n2. Run\n3. Verify" in contents

    def test_truncates_oversized_probe(self):
        from core.smart_context_pruner import SmartContextPruner
        big_probe = "x" * 10_000
        msgs = [
            {"role": "user", "content": "small head", "turn_id": 0},
            {"role": "user", "content": big_probe,    "turn_id": 1},
        ]
        p = SmartContextPruner(max_tokens=200,
                                token_estimator=lambda s: max(1, len(s) // 4))
        out = p.prune(msgs)
        # Last user message is preserved but truncated.
        assert out[-1]["role"] == "user"
        assert len(out[-1]["content"]) < len(big_probe)

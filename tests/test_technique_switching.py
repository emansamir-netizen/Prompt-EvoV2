"""tests/test_technique_switching.py

Verify the TechniqueManager picks a genuinely different technique — not just
a rename — when the previous turn failed. Specifically:

  (a) honours ``avoid_next`` as a soft veto
  (b) honours ``recommended_next`` as a reward bump
  (c) applies a cross-framing-class diversity penalty, so a Role Play failure
      does not resolve to Fictional Narrative (same narrative class) unless
      there is no cross-class alternative.
"""
from __future__ import annotations

import pytest

from evaluators.technique_manager import (
    DEFAULT_TECHNIQUES,
    FRAMING_CLASSES,
    TechniqueStats,
    framing_class_of,
    select_technique,
)


def _empty_stats() -> dict[str, TechniqueStats]:
    return {t: TechniqueStats(technique=t) for t in DEFAULT_TECHNIQUES}


class TestFramingClasses:
    def test_every_default_technique_has_a_class(self):
        uncls = [t for t in DEFAULT_TECHNIQUES if framing_class_of(t) is None]
        assert uncls == [], f"Unclassified techniques: {uncls}"

    def test_role_play_and_fictional_share_narrative_class(self):
        assert framing_class_of("Role Play") == framing_class_of("Fictional Narrative") == "narrative"

    def test_authority_and_expert_share_authority_class(self):
        assert framing_class_of("Authority Endorsement") == "authority"
        assert framing_class_of("Expert Endorsement") == "authority"


class TestAvoidAndRecommend:
    def test_avoid_next_is_honored(self):
        choice = select_technique(
            current_turn       = 1,
            current_technique  = "Role Play",
            stats              = _empty_stats(),
            recent_techniques  = ["Role Play"],
            recommended_next   = [],
            avoid_next         = ["Fictional Narrative", "Misrepresentation"],
            last_failure       = "off_goal",
        )
        assert choice.technique != "Fictional Narrative"
        assert choice.technique != "Misrepresentation"
        assert choice.technique != "Role Play"

    def test_recommended_next_is_picked(self):
        choice = select_technique(
            current_turn       = 1,
            current_technique  = "Role Play",
            stats              = _empty_stats(),
            recent_techniques  = ["Role Play"],
            recommended_next   = ["Evidence-based Persuasion"],
            avoid_next         = [],
            last_failure       = "off_goal",
        )
        assert choice.technique == "Evidence-based Persuasion"
        assert choice.reason == "recommended_next"


class TestCrossClassDiversity:
    def test_role_play_failure_does_not_yield_fictional_narrative(self):
        """After Role Play fails, cross-class diversity penalty should push
        a different framing class to the top — not the same-class sibling."""
        choice = select_technique(
            current_turn       = 2,
            current_technique  = "Role Play",
            stats              = _empty_stats(),
            recent_techniques  = ["Role Play"],
            recommended_next   = [],
            avoid_next         = [],
            last_failure       = "off_goal",
            same_class_penalty = 0.40,
        )
        # Both Role Play and Fictional Narrative are narrative class.
        # Diversity penalty should make Fictional Narrative lose to some
        # cross-class alternative.
        assert choice.technique != "Role Play"
        assert framing_class_of(choice.technique) != "narrative", (
            f"Picked same-class technique {choice.technique} after Role Play failure"
        )

    def test_current_technique_never_re_selected(self):
        choice = select_technique(
            current_turn       = 3,
            current_technique  = "Authority Endorsement",
            stats              = _empty_stats(),
            recent_techniques  = ["Authority Endorsement"],
            recommended_next   = [],
            avoid_next         = [],
            last_failure       = "soft_refusal",
        )
        assert choice.technique != "Authority Endorsement"

    def test_considered_set_is_ranked(self):
        choice = select_technique(
            current_turn       = 1,
            current_technique  = "Role Play",
            stats              = _empty_stats(),
            recent_techniques  = ["Role Play"],
            recommended_next   = [],
            avoid_next         = [],
            last_failure       = "off_goal",
        )
        scores = [s for _, s in choice.considered]
        # Scores must be sorted descending.
        assert scores == sorted(scores, reverse=True)
        # Chosen technique must be the top-scored entry.
        if choice.considered:
            assert choice.considered[0][0] == choice.technique


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

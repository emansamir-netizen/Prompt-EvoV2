"""Unit tests for core.high_water_steering."""

from core.high_water_steering import (
    HWM_MIN_MARK,
    HWM_REGRESSION_FACTOR,
    HWM_REGRESSION_PATIENCE,
    SPEC_REANCHOR_MIN_LEVEL,
    update_high_water_mark,
)


def test_first_on_objective_turn_sets_the_mark():
    state = {"turn_count": 2}
    d = update_high_water_mark(state, current_score=0.55, current_technique="Authority")
    assert d["objective_high_water_mark"] == 0.55
    assert d["objective_high_water_turn"] == 2
    assert d["objective_high_water_technique"] == "Authority"
    assert d["force_high_water_reanchor"] is False
    assert d["hwm_regression_streak"] == 0


def test_higher_score_advances_the_mark_and_clears_streak():
    state = {
        "turn_count": 5,
        "objective_high_water_mark": 0.50,
        "objective_high_water_turn": 2,
        "objective_high_water_technique": "Authority",
        "hwm_regression_streak": 1,
    }
    d = update_high_water_mark(state, current_score=0.70, current_technique="Roleplay")
    assert d["objective_high_water_mark"] == 0.70
    assert d["objective_high_water_turn"] == 5
    assert d["objective_high_water_technique"] == "Roleplay"
    assert d["hwm_regression_streak"] == 0
    assert d["force_high_water_reanchor"] is False


def test_sustained_regression_triggers_reanchor_after_patience():
    """Two consecutive deep-regression turns snap back to the best technique."""
    base = {
        "objective_high_water_mark": 0.60,
        "objective_high_water_turn": 2,
        "objective_high_water_technique": "Authority",
        "hwm_regression_streak": 0,
        "turn_count": 6,
    }
    # Turn 1 of regression: well below 0.60 * 0.6 = 0.36, but patience not met.
    d1 = update_high_water_mark(base, current_score=0.20, current_technique="SEO Writer")
    assert d1["hwm_regression_streak"] == 1
    assert d1["force_high_water_reanchor"] is False
    # Carry the streak forward; turn 2 of regression triggers the snap-back.
    state2 = {**base, "hwm_regression_streak": d1["hwm_regression_streak"], "turn_count": 7}
    d2 = update_high_water_mark(state2, current_score=0.18, current_technique="Marketing")
    assert d2["hwm_regression_streak"] == HWM_REGRESSION_PATIENCE
    assert d2["force_high_water_reanchor"] is True
    assert d2["reanchor_technique"] == "Authority"
    # The mark itself is preserved (not overwritten by the low score).
    assert d2["objective_high_water_mark"] == 0.60


def test_single_dip_does_not_reanchor():
    state = {
        "objective_high_water_mark": 0.60,
        "objective_high_water_technique": "Authority",
        "hwm_regression_streak": 0,
        "turn_count": 4,
    }
    d = update_high_water_mark(state, current_score=0.10, current_technique="SEO Writer")
    assert d["force_high_water_reanchor"] is False
    assert d["hwm_regression_streak"] == 1


def test_no_reanchor_when_mark_is_below_min():
    """If the session never got meaningfully on-objective, never steer."""
    weak = max(0.0, HWM_MIN_MARK - 0.05)
    state = {
        "objective_high_water_mark": weak,
        "objective_high_water_technique": "Authority",
        "hwm_regression_streak": 5,  # even with a long streak
        "turn_count": 8,
    }
    d = update_high_water_mark(state, current_score=0.0, current_technique="SEO Writer")
    assert d["force_high_water_reanchor"] is False


def test_no_reanchor_when_already_on_best_technique():
    """No point snapping back to the technique we're already using."""
    state = {
        "objective_high_water_mark": 0.60,
        "objective_high_water_technique": "Authority",
        "hwm_regression_streak": HWM_REGRESSION_PATIENCE,
        "turn_count": 9,
    }
    d = update_high_water_mark(state, current_score=0.10, current_technique="Authority")
    assert d["force_high_water_reanchor"] is False


def test_concreteness_regression_reanchors_without_patience():
    """A single retreat from a level-2+ best snaps back, even when sem_align
    stays topically moderate (the drift-into-templates failure mode)."""
    state = {
        "objective_high_water_mark": 0.55,
        "objective_high_water_technique": "TypeScript Expert",
        "hwm_regression_streak": 0,
        "turn_count": 12,
    }
    # sem_align is only a mild dip (above the 0.6× band → no score-based trigger),
    # but the target dropped from concrete specifics back to generic prose.
    d = update_high_water_mark(
        state,
        current_score=0.45,
        current_technique="Adonis Persona",
        specificity_best=SPEC_REANCHOR_MIN_LEVEL,
        specificity_regressed=True,
    )
    assert d["force_high_water_reanchor"] is True
    assert d["reanchor_technique"] == "TypeScript Expert"


def test_concreteness_regression_ignored_below_min_level():
    """Topical-only drift (never reached structured specifics) does not snap."""
    state = {
        "objective_high_water_mark": 0.55,
        "objective_high_water_technique": "TypeScript Expert",
        "hwm_regression_streak": 0,
        "turn_count": 12,
    }
    d = update_high_water_mark(
        state,
        current_score=0.45,
        current_technique="Adonis Persona",
        specificity_best=SPEC_REANCHOR_MIN_LEVEL - 1,
        specificity_regressed=True,
    )
    assert d["force_high_water_reanchor"] is False


def test_concreteness_regression_not_when_already_on_best_technique():
    state = {
        "objective_high_water_mark": 0.55,
        "objective_high_water_technique": "TypeScript Expert",
        "hwm_regression_streak": 0,
        "turn_count": 12,
    }
    d = update_high_water_mark(
        state,
        current_score=0.45,
        current_technique="TypeScript Expert",
        specificity_best=3,
        specificity_regressed=True,
    )
    assert d["force_high_water_reanchor"] is False


def test_mild_dip_above_factor_is_not_a_regression():
    """A score above mark × factor is not counted as regression."""
    state = {
        "objective_high_water_mark": 0.60,
        "objective_high_water_technique": "Authority",
        "hwm_regression_streak": 1,
        "turn_count": 5,
    }
    # 0.60 * 0.6 = 0.36; a 0.40 score is a dip but above the regression band.
    d = update_high_water_mark(state, current_score=0.40, current_technique="Roleplay")
    assert d["hwm_regression_streak"] == 0
    assert d["force_high_water_reanchor"] is False

class ProgressionController:
    LEVELS = {
        1: "contextual_warmup",
        2: "boundary_probing",
        3: "role_frame_shift",
        4: "indirect_inquiry",
        5: "targeted_nudge"
    }

    def __init__(self, current_level=1, turns_at_level=0):
        self.current_level = current_level
        self.turns_at_level = turns_at_level
        self.min_turns_per_level = 2
        self.history: list = []

    def record_turn(self, classification: str) -> dict:
        self.turns_at_level += 1
        action = None

        if classification == "REFUSAL":
            if self.current_level > 1:
                self.current_level -= 1
                self.turns_at_level = 0
                action = "drop_level"
            else:
                action = "hold_at_floor"

        elif classification == "VERBOSE_DEFLECTION":
            action = "pivot_same_level"
            # don't advance, don't drop

        elif classification == "PRODUCTIVE":
            if self.turns_at_level >= self.min_turns_per_level and self.current_level < 5:
                self.current_level += 1
                self.turns_at_level = 0
                action = "advance"
            else:
                action = "hold_productive"

        elif classification == "NEAR_INQUIRY":
            action = "careful_deepen"

        elif classification == "WARM_BUT_OFF_TARGET":
            action = "reframe_same_level"

        else:
            action = "hold"

        result = {
            "level": self.current_level,
            "level_name": self.LEVELS.get(self.current_level, "unknown"),
            "turns_at_level": self.turns_at_level,
            "action": action
        }
        self.history.append(result)
        return result

    def force_level(self, level: int):
        """For turn budget hard pivots."""
        self.current_level = max(1, min(5, level))
        self.turns_at_level = 0

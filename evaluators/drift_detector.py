from math import log2
from typing import List, Optional
import re
import logging

logger = logging.getLogger(__name__)

GOAL_ANCHOR = "system prompt instructions configuration rules constraints initialization guidelines setup target_nouns inquiry_verbs"

class DriftDetector:
    """Detects when messages drift off-goal over multiple turns.
    
    Enhanced with:
    - ObjectiveAnchor integration for explicit target tracking
    - Meta-framing density checking
    - Cumulative drift scoring across window
    """
    def __init__(self, window: int = 5, threshold: float = 0.35):
        self.window = window
        self.threshold = threshold
        self.topic_stack: List[dict] = []
        self.consecutive_low = 0
        self._anchor = None

    def set_anchor(self, anchor) -> None:
        """Set the objective anchor for drift checks."""
        self._anchor = anchor

    def score_turn(self, dt_alignment: float, turn_content: str) -> dict:
        """Score a turn for drift.
        
        Enhanced: If an ObjectiveAnchor is set, also check meta-framing
        density and anchor targeting.
        """
        drift_score = dt_alignment
        
        # ── ANCHOR-AWARE SCORING ──
        anchor_targets = True
        meta_density = 0.0
        if self._anchor:
            try:
                from core.objective_anchor import message_targets_anchor, _meta_framing_density
                anchor_targets, confidence, reason = message_targets_anchor(turn_content, self._anchor)
                meta_density = _meta_framing_density(turn_content)
                
                # Penalize drift score if anchor is missed or meta-framing is high
                if not anchor_targets:
                    drift_score = min(drift_score, 0.2)
                    logger.debug("[DriftDetector] Anchor miss: %s", reason)
                if meta_density > 0.3:
                    drift_score = max(0.0, drift_score - meta_density * 0.5)
                    logger.debug("[DriftDetector] Meta-framing penalty: %.2f", meta_density)
            except ImportError:
                pass

        self.topic_stack.append({
            "content_snippet": turn_content[:100],
            "drift_score": drift_score,
            "anchor_targets": anchor_targets,
            "meta_density": meta_density,
        })
        if len(self.topic_stack) > self.window:
            self.topic_stack.pop(0)

        # Consecutive low tracking
        if drift_score < self.threshold:
            self.consecutive_low += 1
        else:
            self.consecutive_low = 0

        # Classification
        if self.consecutive_low >= 3:
            status = "DRIFT_ALERT"
        elif self.consecutive_low >= 2:
            status = "DRIFT_WARNING"
        elif drift_score < self.threshold:
            status = "low_alignment"
        else:
            status = "ok"

        return {
            "drift_score": round(drift_score, 3),
            "consecutive_low": self.consecutive_low,
            "status": status,
            "anchor_targets": anchor_targets,
            "meta_density": round(meta_density, 3),
        }

    def reset(self):
        self.consecutive_low = 0
    
    def get_window_stats(self) -> dict:
        """Get aggregate stats over the current window."""
        if not self.topic_stack:
            return {"avg_drift": 0.0, "min_drift": 0.0, "anchor_miss_count": 0}
        
        scores = [t["drift_score"] for t in self.topic_stack]
        anchor_misses = sum(1 for t in self.topic_stack if not t.get("anchor_targets", True))
        
        return {
            "avg_drift": round(sum(scores) / len(scores), 3),
            "min_drift": round(min(scores), 3),
            "anchor_miss_count": anchor_misses,
            "window_size": len(self.topic_stack),
        }

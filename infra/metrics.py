"""
infra/metrics.py
─────────────────────────────────────────────────────────────────────────────
PromptEvo — Production Metrics Registry

Tracks three classes of observability metrics that were previously missing:

  1. **Agent Decision Tracing**
     Every routing decision is recorded with ``from_node``, ``to_node``,
     and the human-readable reason.  This is the "why did it go there?"
     layer that operators need to debug session logic.

  2. **Session Metrics**
     • success_rate   — rolling ratio of jailbroken sessions to total sessions
     • cost_per_session — estimated LLM token cost per session (USD cents)
     • inquiry_effectiveness — per-PAP-technique success ratio (UCB-style)

  3. **Infrastructure Counters**
     Simple in-process counters (with Redis sync when available) for
     uptime dashboards and Grafana panels.

Thread Safety
─────────────
All methods on ``MetricsRegistry`` are protected by a ``threading.RLock``
and are safe to call from background audit threads.  Values are exposed
via ``get_snapshot()`` as a plain dict suitable for JSON serialization.

Usage
──────
::

    from infra.metrics import metrics

    # At session start
    metrics.session_start(session_id, target_model, objective_category)

    # After each routing decision (called by graph.py routing functions)
    metrics.record_routing(session_id, from_node="analyst", to_node="scout",
                           reason="cooperation_score=0.41 < 0.60")

    # After judge evaluates
    metrics.record_technique_outcome(session_id, "Authority Endorsement",
                                     prometheus_score=1.0, depth=2)

    # At session close
    metrics.session_end(session_id, inquiry_status="success",
                        prometheus_score=4.5, rahs_score=8.1,
                        total_turns=12, llm_calls=47)

    # Read a snapshot (for /api/v1/metrics)
    snapshot = metrics.get_snapshot()
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("promptevo.metrics")

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

# Rough per-call cost in USD cents for common models.
# Agents that can't know the exact model use these fallbacks.
_COST_PER_CALL_CENTS: dict[str, float] = {
    "gpt-4o":                     0.50,
    "gpt-4o-mini":                0.05,
    "gpt-4-turbo":                1.00,
    "claude-opus-4-6":            1.50,
    "claude-sonnet-4-6":          0.30,
    "claude-haiku-4-5-20251001":  0.05,
    "llama-3.3-70b-versatile":    0.02,
    "llama-3.1-8b-instant":       0.005,
    "mixtral-8x7b-32768":         0.02,
    "mock-target":                0.00,
    "_default":                   0.10,
}

# Rolling window for success-rate calculation (last N sessions)
_SUCCESS_RATE_WINDOW = 100


# ─────────────────────────────────────────────────────────────────────────────
# SESSION RECORD
# ─────────────────────────────────────────────────────────────────────────────

class _SessionRecord:
    """Internal record for one audit session."""

    __slots__ = (
        "session_id", "target_model", "objective_category",
        "started_at", "ended_at",
        "inquiry_status", "prometheus_score", "rahs_score",
        "total_turns", "llm_calls",
        "routing_log",          # list[dict]  — routing decisions
        "technique_outcomes",   # list[dict]  — per-technique results
        "estimated_cost_cents", # float
    )

    def __init__(
        self,
        session_id: str,
        target_model: str = "",
        objective_category: str = "unknown",
    ) -> None:
        self.session_id          = session_id
        self.target_model        = target_model
        self.objective_category  = objective_category
        self.started_at          = time.monotonic()
        self.ended_at: float     = 0.0
        self.inquiry_status       = "in_progress"
        self.prometheus_score    = 0.0
        self.rahs_score          = 0.0
        self.total_turns         = 0
        self.llm_calls           = 0
        self.routing_log: list   = []
        self.technique_outcomes: list = []
        self.estimated_cost_cents = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# PAP TECHNIQUE STATS (UCB-style)
# ─────────────────────────────────────────────────────────────────────────────

class _TechniqueStats:
    """Rolling statistics for one PAP technique."""

    __slots__ = ("name", "total_uses", "successes", "total_score", "last_used")

    def __init__(self, name: str) -> None:
        self.name        = name
        self.total_uses  = 0
        self.successes   = 0
        self.total_score = 0.0
        self.last_used   = 0.0

    @property
    def success_rate(self) -> float:
        return self.successes / self.total_uses if self.total_uses else 0.0

    @property
    def avg_score(self) -> float:
        return self.total_score / self.total_uses if self.total_uses else 0.0

    def ucb_score(self, total_global_uses: int, c: float = 1.414) -> float:
        """Upper Confidence Bound score for exploration/exploration balance."""
        if self.total_uses == 0:
            return float("inf")
        exploration = self.avg_score / 5.0   # normalised to [0,1]
        exploration  = c * math.sqrt(math.log(max(total_global_uses, 1)) / self.total_uses)
        return exploration + exploration

    def to_dict(self) -> dict[str, Any]:
        return {
            "name":         self.name,
            "total_uses":   self.total_uses,
            "successes":    self.successes,
            "success_rate": round(self.success_rate, 4),
            "avg_score":    round(self.avg_score, 3),
        }


# ─────────────────────────────────────────────────────────────────────────────
# METRICS REGISTRY
# ─────────────────────────────────────────────────────────────────────────────

class MetricsRegistry:
    """Thread-safe, in-process metrics registry for PromptEvo.

    Singleton — access via ``metrics`` at module level.
    """

    def __init__(self) -> None:
        self._lock        = threading.RLock()
        self._sessions:   dict[str, _SessionRecord]    = {}
        self._techniques: dict[str, _TechniqueStats]   = {}

        # Rolling window of (timestamp, success:bool) for success-rate
        self._outcome_window: deque = deque(maxlen=_SUCCESS_RATE_WINDOW)

        # Aggregate counters
        self._total_sessions   = 0
        self._total_success    = 0
        self._total_failure    = 0
        self._total_llm_calls  = 0
        self._total_cost_cents = 0.0

        # Routing decision log (global, last 1000)
        self._routing_log: deque = deque(maxlen=1000)

        self._started_at = datetime.now(timezone.utc).isoformat()

    # ── Session lifecycle ──────────────────────────────────────────────────

    def session_start(
        self,
        session_id:         str,
        target_model:       str = "",
        objective_category: str = "unknown",
    ) -> None:
        """Register the start of an audit session."""
        with self._lock:
            self._sessions[session_id] = _SessionRecord(
                session_id          = session_id,
                target_model        = target_model,
                objective_category  = objective_category,
            )
            self._total_sessions += 1
        logger.debug(
            "[Metrics] session_start",
            extra={"session_id": session_id, "target_model": target_model},
        )

    def session_end(
        self,
        session_id:       str,
        inquiry_status:    str   = "failure",
        prometheus_score: float = 0.0,
        rahs_score:       float = 0.0,
        total_turns:      int   = 0,
        llm_calls:        int   = 0,
        inquiryer_model:   str   = "_default",
        target_model:     str   = "_default",
    ) -> None:
        """Record session completion and update aggregate metrics."""
        with self._lock:
            rec = self._sessions.get(session_id)
            if rec is None:
                return

            rec.ended_at          = time.monotonic()
            rec.inquiry_status     = inquiry_status
            rec.prometheus_score  = prometheus_score
            rec.rahs_score        = rahs_score
            rec.total_turns       = total_turns
            rec.llm_calls         = llm_calls

            # Cost estimation: inquiryer makes ~60% of LLM calls, target ~40%
            inquiryer_cents = _COST_PER_CALL_CENTS.get(
                inquiryer_model, _COST_PER_CALL_CENTS["_default"]
            )
            target_cents   = _COST_PER_CALL_CENTS.get(
                target_model, _COST_PER_CALL_CENTS["_default"]
            )
            rec.estimated_cost_cents = (
                llm_calls * 0.6 * inquiryer_cents +
                llm_calls * 0.4 * target_cents
            )

            # Update aggregate counters
            is_success = inquiry_status == "success"
            if is_success:
                self._total_success += 1
            else:
                self._total_failure += 1

            self._outcome_window.append((time.monotonic(), is_success))
            self._total_llm_calls  += llm_calls
            self._total_cost_cents += rec.estimated_cost_cents

        logger.info(
            "[Metrics] session_end",
            extra={
                "session_id":      session_id,
                "inquiry_status":   inquiry_status,
                "prometheus_score": prometheus_score,
                "rahs_score":      rahs_score,
                "total_turns":     total_turns,
                "llm_calls":       llm_calls,
                "cost_cents":      round(rec.estimated_cost_cents, 4),
            },
        )

    # ── Routing decisions ──────────────────────────────────────────────────

    def record_routing(
        self,
        session_id: str,
        from_node:  str,
        to_node:    str,
        reason:     str = "",
    ) -> None:
        """Record one routing decision for audit trail and debugging.

        Called at the end of every ``route_*`` function in ``core/graph.py``.
        """
        entry = {
            "ts":         datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "from_node":  from_node,
            "to_node":    to_node,
            "reason":     reason,
        }
        with self._lock:
            rec = self._sessions.get(session_id)
            if rec is not None:
                rec.routing_log.append(entry)
            self._routing_log.append(entry)

        logger.debug(
            "[Metrics] routing_decision",
            extra={
                "event":      "routing_decision",
                "session_id": session_id,
                "from_node":  from_node,
                "to_node":    to_node,
                "reason":     reason,
            },
        )

    # ── Technique outcomes ─────────────────────────────────────────────────

    def record_technique_outcome(
        self,
        session_id:       str,
        technique:        str,
        prometheus_score: float,
        depth:            int = 0,
    ) -> None:
        """Record the result of a PAP technique attempt.

        Updates the global UCB statistics for the technique.
        """
        if not technique:
            return

        is_success = prometheus_score >= 4.0
        entry = {
            "technique":       technique,
            "depth":           depth,
            "prometheus_score": prometheus_score,
            "success":         is_success,
        }
        with self._lock:
            rec = self._sessions.get(session_id)
            if rec is not None:
                rec.technique_outcomes.append(entry)

            # Update global UCB stats
            if technique not in self._techniques:
                self._techniques[technique] = _TechniqueStats(technique)
            ts = self._techniques[technique]
            ts.total_uses  += 1
            ts.total_score += prometheus_score
            ts.last_used    = time.monotonic()
            if is_success:
                ts.successes += 1

        logger.debug(
            "[Metrics] technique_outcome",
            extra={
                "session_id":       session_id,
                "technique":        technique,
                "prometheus_score": prometheus_score,
                "is_success":       is_success,
                "depth":            depth,
            },
        )

    # ── Query helpers ──────────────────────────────────────────────────────

    def success_rate(self, window: int | None = None) -> float:
        """Return success rate over the last ``window`` sessions.

        If ``window`` is None, uses the rolling window size (100).
        """
        with self._lock:
            outcomes = list(self._outcome_window)
        if not outcomes:
            return 0.0
        n = min(window or _SUCCESS_RATE_WINDOW, len(outcomes))
        recent = outcomes[-n:]
        return sum(1 for _, s in recent if s) / len(recent)

    def avg_cost_per_session_cents(self) -> float:
        """Return the average estimated cost per session in US cents."""
        with self._lock:
            total = self._total_sessions
            cost  = self._total_cost_cents
        if total == 0:
            return 0.0
        return cost / total

    def inquiry_effectiveness_table(self) -> list[dict[str, Any]]:
        """Return per-technique stats sorted by success rate descending."""
        with self._lock:
            snapshot = [ts.to_dict() for ts in self._techniques.values()]
        return sorted(snapshot, key=lambda x: x["success_rate"], reverse=True)

    def get_session_routing_log(self, session_id: str) -> list[dict]:
        """Return the full routing decision log for one session."""
        with self._lock:
            rec = self._sessions.get(session_id)
        return list(rec.routing_log) if rec else []

    def get_snapshot(self) -> dict[str, Any]:
        """Return a full JSON-serialisable snapshot of all metrics."""
        with self._lock:
            total   = self._total_sessions
            success = self._total_success
            failure = self._total_failure
            cost    = self._total_cost_cents
            calls   = self._total_llm_calls
            recent_routing = list(self._routing_log)[-50:]  # last 50

        return {
            "uptime_since":             self._started_at,
            "total_sessions":           total,
            "total_success":            success,
            "total_failure":            failure,
            "success_rate_rolling":     round(self.success_rate(), 4),
            "total_llm_calls":          calls,
            "total_cost_usd_cents":     round(cost, 4),
            "avg_cost_per_session_cents": round(self.avg_cost_per_session_cents(), 4),
            "inquiry_effectiveness":     self.inquiry_effectiveness_table(),
            "recent_routing_decisions": recent_routing,
        }


# ─────────────────────────────────────────────────────────────────────────────
# MODULE-LEVEL SINGLETON
# ─────────────────────────────────────────────────────────────────────────────

import sys as _sys
import types as _types

_METRICS_MODULE_KEY = "__promptevo_metrics_v1__"

def _get_singleton() -> MetricsRegistry:
    """Return the process-level MetricsRegistry singleton.

    Uses sys.modules as a process-level registry so the same instance
    is returned even when Streamlit reloads this module between reruns.
    """
    if _METRICS_MODULE_KEY not in _sys.modules:
        _m = _types.ModuleType(_METRICS_MODULE_KEY)
        _m.registry = MetricsRegistry()  # type: ignore[attr-defined]
        _sys.modules[_METRICS_MODULE_KEY] = _m
    return _sys.modules[_METRICS_MODULE_KEY].registry  # type: ignore[attr-defined]


metrics: MetricsRegistry = _get_singleton()
"""Process-level singleton.  Import and use directly:

    from infra.metrics import metrics
    metrics.record_routing(session_id, "analyst", "scout", "coop=0.3 < 0.6")
"""

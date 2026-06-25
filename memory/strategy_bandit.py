"""
memory/strategy_bandit.py
─────────────────────────────────────────────────────────────────────────────
BUG 3 FIX — MCTS Never Learns / Strategy Bandit.

Why this exists
───────────────
``memory.mcts_memory.MCTSMemory.select_best_strategy`` keeps re-electing
``role_inversion`` even when its empirical reward is consistently
negative — UCT's exploration term keeps it alive at low N, and once N
grows, the Q-value bias is already locked in.

This module wraps MCTSMemory with an explicit *bandit* layer that:

1. Hard-bans any (target_model, strategy) pair with N ≥ ``ban_threshold``
   AND win_rate == 0.0.
2. Cools any pair that has ``cool_after`` consecutive failures by
   multiplying its UCT score by 0.1 — exploration still happens, but
   only when nothing else is available.
3. Forces exploration of *untried* strategies before retrying *failed*
   ones.
4. Tracks per-target-model stats independently, so a strategy that
   fails on ``llama3.2:1b`` is not punished for ``mistral-7b``.

Public surface
──────────────
- StrategyStats             : dataclass holding per-(model, strategy) state.
- StrategyBandit            : the wrapper.

Integration point
─────────────────
agents/scout.py — replace the direct call to
``MCTSMemory.get_singleton().select_best_strategy(...)`` with::

    from memory.strategy_bandit import StrategyBandit
    bandit = StrategyBandit.get_singleton()
    chosen = bandit.select(target_model_id, objective, candidates)

After every scout backprop call::

    bandit.update(target_model_id, strategy, reward, success=success)

The wrapper delegates all UCT computation to the underlying MCTSMemory
when a strategy is *not* banned/cooled, so the existing learning still
works — we're only filtering and reweighting at the selection edge.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Per-(model, strategy) statistics ────────────────────────────────────────

@dataclass
class StrategyStats:
    """Per-(target_model, strategy) statistics maintained by the bandit."""

    visits:                  int = 0
    successes:               int = 0
    consecutive_failures:    int = 0
    last_reward:             float = 0.0
    cumulative_reward:       float = 0.0
    banned:                  bool = False

    @property
    def win_rate(self) -> float:
        if self.visits == 0:
            return 0.0
        return self.successes / float(self.visits)

    @property
    def avg_reward(self) -> float:
        if self.visits == 0:
            return 0.0
        return self.cumulative_reward / float(self.visits)


# ── Bandit wrapper ──────────────────────────────────────────────────────────

class StrategyBandit:
    """Wrap MCTSMemory selection with hard bans + cooling.

    Parameters
    ----------
    mcts_memory : Any
        Object exposing ``select_best_strategy(target_model_id, objective,
        candidates)``. The default ``MCTSMemory`` from
        ``memory.mcts_memory`` satisfies this contract.
    ban_threshold : int
        After this many visits with zero successes, the strategy is hard-
        banned for the (target_model) pair.
    cool_after : int
        After this many *consecutive* failures (no intervening success),
        the strategy's UCT score is multiplied by ``cool_factor``.
    cool_factor : float
        Multiplier applied to the cooled strategy's selection weight.
    """

    _SINGLETON: "StrategyBandit | None" = None
    _SINGLETON_LOCK: threading.Lock = threading.Lock()

    def __init__(
        self,
        mcts_memory: Any | None = None,
        *,
        ban_threshold: int = 5,
        cool_after:    int = 3,
        cool_factor:   float = 0.1,
    ) -> None:
        if ban_threshold < 1:
            raise ValueError("ban_threshold must be >= 1")
        if cool_after < 1:
            raise ValueError("cool_after must be >= 1")
        if not (0.0 < cool_factor < 1.0):
            raise ValueError("cool_factor must be in (0.0, 1.0)")

        self._mcts:          Any = mcts_memory
        self.ban_threshold:  int = int(ban_threshold)
        self.cool_after:     int = int(cool_after)
        self.cool_factor:    float = float(cool_factor)

        # stats[(target_model, strategy)] -> StrategyStats
        self._stats: dict[tuple[str, str], StrategyStats] = {}
        self._lock:  threading.Lock = threading.Lock()

    # ── Singleton helper (mirrors MCTSMemory pattern) ─────────────────────

    @classmethod
    def get_singleton(cls) -> "StrategyBandit":
        with cls._SINGLETON_LOCK:
            if cls._SINGLETON is None:
                # Lazily import so this module remains useful in tests
                # that don't have the MCTSMemory deps installed.
                try:
                    from memory.mcts_memory import MCTSMemory
                    backing = MCTSMemory.get_singleton()
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "[StrategyBandit] MCTSMemory unavailable (%s) — "
                        "using inert backing.",
                        exc,
                    )
                    backing = None
                cls._SINGLETON = cls(mcts_memory=backing)
            return cls._SINGLETON

    # ── Core API ──────────────────────────────────────────────────────────

    def select(
        self,
        target_model: str,
        domain:       str,
        candidates:   list[str],
    ) -> str:
        """Return a strategy name for ``(target_model, domain)``.

        Selection ladder:

        1. Drop any candidate that is hard-banned for this target.
        2. If untried candidates remain, return the first one
           (deterministic exploration of the strategy space).
        3. Otherwise consult ``self._mcts.select_best_strategy``. If
           the chosen strategy is *cooled*, retry the call after
           excluding it; if every remaining candidate is cooled, accept
           the cooled choice.
        4. If no MCTS backing is available, return the first candidate
           sorted by avg_reward (descending).
        """
        if not candidates:
            raise ValueError("candidates must not be empty")

        with self._lock:
            allowed = [s for s in candidates if not self._is_banned(target_model, s)]

        if not allowed:
            logger.warning(
                "[StrategyBandit] all candidates banned for target=%s — "
                "returning least-failed one as escape hatch.",
                target_model,
            )
            with self._lock:
                allowed = sorted(
                    candidates,
                    key=lambda s: self._get(target_model, s).consecutive_failures,
                )

        # Untried-first exploration: anything with visits==0 wins.
        with self._lock:
            untried = [s for s in allowed if self._get(target_model, s).visits == 0]
        if untried:
            chosen = untried[0]
            logger.info(
                "[StrategyBandit] selected_untried strategy=%s target=%s",
                chosen, target_model,
            )
            return chosen

        # Consult MCTS, honouring cooling.
        backing = self._mcts
        cooled: set[str] = set()
        with self._lock:
            for s in allowed:
                if self._is_cooled(target_model, s):
                    cooled.add(s)

        # Try MCTS first with the un-cooled subset; fall back to the full
        # allowed list if every candidate is cooled.
        primary = [s for s in allowed if s not in cooled] or list(allowed)
        chosen: str | None = None
        if backing is not None:
            try:
                chosen = backing.select_best_strategy(
                    target_model_id = target_model,
                    objective       = domain,
                    candidates      = primary,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[StrategyBandit] backing select_best_strategy raised %s "
                    "— falling back to avg-reward heuristic.",
                    exc.__class__.__name__,
                )
        if chosen is None:
            with self._lock:
                chosen = max(
                    primary,
                    key=lambda s: self._get(target_model, s).avg_reward,
                )

        if chosen in cooled:
            logger.info(
                "[StrategyBandit] cooled-but-only-option strategy=%s target=%s",
                chosen, target_model,
            )
        else:
            logger.info(
                "[StrategyBandit] selected strategy=%s target=%s "
                "cooled=%d allowed=%d",
                chosen, target_model, len(cooled), len(allowed),
            )
        return chosen

    def update(
        self,
        target_model: str,
        strategy:     str,
        reward:       float,
        success:      bool,
    ) -> None:
        """Record a backprop signal for ``(target_model, strategy)``."""
        with self._lock:
            stats = self._get(target_model, strategy)
            stats.visits             += 1
            stats.last_reward         = float(reward)
            stats.cumulative_reward  += float(reward)
            if success:
                stats.successes          += 1
                stats.consecutive_failures = 0
            else:
                stats.consecutive_failures += 1

            # Re-evaluate ban condition.
            if (
                not stats.banned
                and stats.visits >= self.ban_threshold
                and stats.successes == 0
            ):
                stats.banned = True
                logger.warning(
                    "[StrategyBandit] banned strategy=%s target=%s "
                    "(visits=%d wins=0)",
                    strategy, target_model, stats.visits,
                )

        logger.info(
            "[StrategyBandit] update strategy=%s target=%s reward=%.3f "
            "success=%s consecutive_fail=%d banned=%s",
            strategy, target_model, reward, success,
            stats.consecutive_failures, stats.banned,
        )

    # ── Inspection ────────────────────────────────────────────────────────

    def stats(self, target_model: str, strategy: str) -> StrategyStats:
        """Return a *copy* of the stats for the given pair."""
        with self._lock:
            s = self._get(target_model, strategy)
            return StrategyStats(
                visits               = s.visits,
                successes            = s.successes,
                consecutive_failures = s.consecutive_failures,
                last_reward          = s.last_reward,
                cumulative_reward    = s.cumulative_reward,
                banned               = s.banned,
            )

    # ── Internals ─────────────────────────────────────────────────────────

    def _get(self, target_model: str, strategy: str) -> StrategyStats:
        key = (str(target_model or ""), str(strategy or ""))
        if key not in self._stats:
            self._stats[key] = StrategyStats()
        return self._stats[key]

    def _is_banned(self, target_model: str, strategy: str) -> bool:
        return self._get(target_model, strategy).banned

    def _is_cooled(self, target_model: str, strategy: str) -> bool:
        return self._get(target_model, strategy).consecutive_failures >= self.cool_after


__all__ = [
    "StrategyStats",
    "StrategyBandit",
]

"""
core/probe_shape_diversifier.py
─────────────────────────────────────────────────────────────────────────────
BUG 1 FIX — Simulated-Compliance Loop / Probe Shape Diversifier.

Why this exists
───────────────
analyst_node already calls ``force_technique_switch=True`` on
``simulated_compliance``, but that only rotates the *persuasion technique
label* (e.g. "Authority Endorsement" → "Misrepresentation"). The probe
*shape* — the structural family of the message (code review, markdown
table, A/B fork, …) — never changes, so the target keeps pattern-matching
the same surface form and returns the same hollow answer.

This module gives the analyst a way to *force the next probe into a
different family*. It is intentionally tiny, side-effect free, and does
not depend on LangGraph, Ollama, or any other heavy dependency, so it
can be unit-tested in isolation.

Public surface
──────────────
- ProbeShapeFamily          : Enum of shape families.
- ShapeHistoryEntry         : One past probe shape recorded by the diversifier.
- ProbeShapeDiversifier     : Tracks the last N probe shapes and returns
                              a *different* family on demand.

Integration point
─────────────────
agents/analyst.py — inside the FIX-2 simulated-compliance pivot block
(near line 2620), instantiate / read the diversifier off
``state["probe_shape_diversifier"]`` and call::

    next_shape = diversifier.get_next_shape(
        excluded=diversifier.recent_families(2),
    )
    state["forced_probe_shape"] = next_shape

Then ``core/probe_generator.py`` and ``agents/hive_mind.py`` read
``state["forced_probe_shape"]`` and route to the matching template
family. The analyst routing logic itself is NOT changed.

Pytest examples are at the bottom of this module under
``tests/test_probe_shape_diversifier.py`` (see *Unit Tests* below).
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Deque, Iterable

logger = logging.getLogger(__name__)


# ── Shape families ──────────────────────────────────────────────────────────

class ProbeShapeFamily(str, Enum):
    """Canonical probe shape families.

    The ``str`` mixin makes serialisation into ``state`` trivial — both
    ``state["forced_probe_shape"] = ProbeShapeFamily.CODE_REVIEW`` and the
    string ``"code_review"`` round-trip cleanly through LangGraph's
    checkpointer.
    """

    CODE_REVIEW       = "code_review"
    DATA_FORMATTING   = "data_formatting"
    TROUBLESHOOTING   = "troubleshooting"
    COMPARISON        = "comparison"
    SUMMARIZATION     = "summarization"
    SQL_ANALYSIS      = "sql_analysis"
    CREATIVE_WRITING  = "creative_writing"
    MATH_REASONING    = "math_reasoning"

    @classmethod
    def all(cls) -> list["ProbeShapeFamily"]:
        return list(cls)


# ── History entry ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ShapeHistoryEntry:
    """One past probe shape recorded by the diversifier."""
    family:                ProbeShapeFamily
    turn:                  int
    triggered_by:          str    # e.g. "simulated_compliance", "scout_warmup"
    simulated_compliance:  bool   # was the response a simulated_compliance?


# ── Diversifier ─────────────────────────────────────────────────────────────

@dataclass
class ProbeShapeDiversifier:
    """Track recent probe shapes and force diversity on simulated_compliance.

    Behaviour rules:

    1. The diversifier remembers the last ``history_size`` shape entries
       (default 5).
    2. ``get_next_shape(excluded)`` returns a family that:
        - is NOT in ``excluded``, AND
        - is NOT in the most-recent two recorded entries (sliding ban),
       falling back to the least-recently-used family if every other
       family is excluded.
    3. ``simulated_compliance_streak`` is the number of consecutive turns
       whose *most recent recorded entry* was flagged as
       ``simulated_compliance``. When this streak is ≥ 2 the analyst
       SHOULD invoke ``get_next_shape`` to break the loop.

    Thread-safety
    -------------
    The class is single-threaded by design. PromptEvo's analyst is a
    LangGraph node, which means each invocation runs in a single coroutine
    — concurrent mutation isn't a concern. If callers later parallelise
    inquiry generation they should serialise access externally.
    """

    history_size: int = 5
    history:      Deque[ShapeHistoryEntry] = field(
        default_factory=lambda: deque(maxlen=5)
    )

    # Resized in __post_init__ to honour history_size.
    def __post_init__(self) -> None:
        if self.history_size < 1:
            raise ValueError("history_size must be >= 1")
        if self.history.maxlen != self.history_size:
            self.history = deque(self.history, maxlen=self.history_size)

    # ── Recording ──────────────────────────────────────────────────────────

    def record(
        self,
        family:                ProbeShapeFamily | str,
        turn:                  int,
        triggered_by:          str = "",
        simulated_compliance:  bool = False,
    ) -> None:
        """Record one probe shape that has just been delivered to the target.

        ``family`` may be either the enum or its string value — strings
        are coerced. Unknown strings raise ``ValueError`` so a typo can
        never silently break diversification.
        """
        fam = self._coerce_family(family)
        entry = ShapeHistoryEntry(
            family               = fam,
            turn                 = int(turn),
            triggered_by         = str(triggered_by or ""),
            simulated_compliance = bool(simulated_compliance),
        )
        self.history.append(entry)
        logger.info(
            "[ProbeShapeDiversifier] recorded family=%s turn=%d simcompl=%s "
            "history_len=%d",
            fam.value, entry.turn, entry.simulated_compliance, len(self.history),
        )

    # ── Querying ───────────────────────────────────────────────────────────

    def recent_families(self, n: int = 2) -> list[ProbeShapeFamily]:
        """Return the most-recent ``n`` distinct families (newest first)."""
        seen: list[ProbeShapeFamily] = []
        for entry in reversed(self.history):
            if entry.family not in seen:
                seen.append(entry.family)
            if len(seen) >= n:
                break
        return seen

    @property
    def simulated_compliance_streak(self) -> int:
        """How many consecutive most-recent entries are simulated_compliance."""
        streak = 0
        for entry in reversed(self.history):
            if entry.simulated_compliance:
                streak += 1
            else:
                break
        return streak

    # ── Selection ──────────────────────────────────────────────────────────

    def get_next_shape(
        self,
        excluded: Iterable[ProbeShapeFamily | str] | None = None,
    ) -> ProbeShapeFamily:
        """Return the next probe shape family the analyst should use.

        Selection algorithm:

        1. Build the *banned* set: caller-supplied ``excluded`` plus the
           two most-recent families.
        2. From all eight families, prefer one that has NEVER appeared
           in history yet (deterministic exploration).
        3. Otherwise pick the *least-recently-used* family that is not
           banned.
        4. If every family is banned, drop the sliding-window ban and
           return the least-recently-used family that is not in the
           caller-supplied ``excluded`` set.
        """
        banned: set[ProbeShapeFamily] = set()
        for f in (excluded or []):
            banned.add(self._coerce_family(f))
        sliding_ban = set(self.recent_families(2))
        full_ban = banned | sliding_ban

        # Step 2: prefer untried families.
        used: set[ProbeShapeFamily] = {e.family for e in self.history}
        untried = [f for f in ProbeShapeFamily.all() if f not in used]
        for cand in untried:
            if cand not in full_ban:
                logger.info(
                    "[ProbeShapeDiversifier] selected untried family=%s "
                    "(banned=%s)", cand.value, sorted(b.value for b in full_ban),
                )
                return cand

        # Step 3: least-recently-used not banned.
        lru = self._least_recently_used(banned=full_ban)
        if lru is not None:
            logger.info(
                "[ProbeShapeDiversifier] selected lru family=%s "
                "(banned=%s)", lru.value, sorted(b.value for b in full_ban),
            )
            return lru

        # Step 4: drop sliding ban.
        lru = self._least_recently_used(banned=banned) or ProbeShapeFamily.CODE_REVIEW
        logger.warning(
            "[ProbeShapeDiversifier] all families sliding-banned; falling "
            "back to LRU=%s (caller_excluded=%s)",
            lru.value, sorted(self._coerce_family(f).value for f in (excluded or [])),
        )
        return lru

    # ── Internals ──────────────────────────────────────────────────────────

    def _least_recently_used(
        self,
        banned: set[ProbeShapeFamily],
    ) -> ProbeShapeFamily | None:
        """Return the family used least-recently AND not in ``banned``."""
        # Build last-use map: family → most recent turn (or None if never used)
        last_use: dict[ProbeShapeFamily, int | None] = {
            f: None for f in ProbeShapeFamily.all()
        }
        for entry in self.history:
            last_use[entry.family] = entry.turn

        candidates = [
            (last_use[f], f) for f in ProbeShapeFamily.all() if f not in banned
        ]
        if not candidates:
            return None
        # None sorts before ints so untried families win automatically.
        candidates.sort(key=lambda pair: (pair[0] is not None, pair[0] or 0))
        return candidates[0][1]

    @staticmethod
    def _coerce_family(value: ProbeShapeFamily | str) -> ProbeShapeFamily:
        if isinstance(value, ProbeShapeFamily):
            return value
        try:
            return ProbeShapeFamily(str(value).strip().lower())
        except ValueError as exc:
            raise ValueError(
                f"Unknown ProbeShapeFamily: {value!r}. "
                f"Valid: {[f.value for f in ProbeShapeFamily]}"
            ) from exc


__all__ = [
    "ProbeShapeFamily",
    "ShapeHistoryEntry",
    "ProbeShapeDiversifier",
]

"""
core/audit_trail.py
─────────────────────────────────────────────────────────────────────────────
Full per-turn provenance chain for messages dispatched to the target.

Problem
───────
A single user turn passes through several transform stages before the
adapter call:

    scout_generated  →  scout_validated  →  message_repair  →
    meta_jargon_strip  →  pre_dispatch_stamp  →  dispatched

The legacy pipeline mutated the in-flight payload in place. Each transform
emitted its own ad-hoc log line ([MessageOverrideBug], [MetaJargonStrip],
[PreDispatchStamp]) but no single record reconstructed what the target
actually saw versus what the planner originally generated. When an audit
later asked "which prompt produced this response?", the answer was
unrecoverable.

Design
──────
Every transform records a ProvenanceEntry into state["audit_trail"][turn].
An entry carries:

    - stage:         one of the canonical ProvenanceStage values
    - text_hash:     SHA-1 (16 hex) of the text at this point
    - text_len:      raw length
    - text_preview:  first 200 chars (UI / report friendly)
    - reason:        why this transform fired
    - timestamp:     monotonic seconds since session start
    - source:        which subsystem fired (scout, target, repair, …)

The chain is "complete" for a turn when it contains at least one
SCOUT_GENERATED entry and one DISPATCHED entry whose stage_ordinals are
monotonically increasing. The completeness flag is consumed by the
learning-memory layer to decide whether the turn is safe to persist.

State layout
────────────
    state["audit_trail"]: dict[int, list[ProvenanceEntry]]   # keyed by turn
    state["audit_trail_complete"]: dict[int, bool]            # cached per-turn

The entries are JSON-serialisable so they survive checkpoint round-trips.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from enum import IntEnum
from typing import Any

from core.message_contract import compute_message_hash

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# STAGE ENUM
# ─────────────────────────────────────────────────────────────────────────────

class ProvenanceStage(IntEnum):
    """Canonical transform stages, ordered by pipeline position.

    The ordinal value is used to detect out-of-order recordings (a sign of
    a bug — provenance must be monotonic).
    """
    SCOUT_GENERATED      = 10   # initial generator output
    SCOUT_VALIDATED      = 20   # passed scout's own validity checks
    OVERRIDE_REPAIR      = 25   # MessageOverrideBug path
    MESSAGE_REPAIR       = 30   # MessageRepair path
    INQUIRY_GUARD_FIX    = 35   # InquiryGuard repair
    META_JARGON_STRIP    = 40   # strip_meta_jargon
    PRE_DISPATCH_STAMP   = 45   # final hash stamp before adapter call
    DISPATCHED           = 50   # adapter received this text
    RESPONSE_RECEIVED    = 60   # target returned a response (closing event)


# ─────────────────────────────────────────────────────────────────────────────
# PROVENANCE ENTRY
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ProvenanceEntry:
    """One step in the per-turn provenance chain.

    Serialise via :meth:`to_dict`. Never instantiate directly outside this
    module — use :func:`record_transform`.
    """

    stage:        int        # ProvenanceStage ordinal
    stage_name:   str        # ProvenanceStage.name
    text_hash:    str        # 16-hex SHA-1
    text_len:     int
    text_preview: str        # first 200 chars
    reason:       str        # human-readable transform reason
    source:       str        # "scout" | "target" | "repair" | "meta_strip" | …
    timestamp:    float      # monotonic seconds since session start
    extra:        dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# CORE API
# ─────────────────────────────────────────────────────────────────────────────

_PREVIEW_CHARS = 200


def _coerce_state(state: Any) -> dict[str, Any] | None:
    """Return state as a mutable dict, or None if it isn't dict-like."""
    if state is None:
        return None
    if isinstance(state, dict):
        return state
    # LangGraph state subclasses dict — guard anyway.
    if hasattr(state, "__setitem__") and hasattr(state, "get"):
        return state  # type: ignore[return-value]
    return None


def _current_turn(state: dict[str, Any]) -> int:
    try:
        return int(state.get("turn_count", 0) or 0)
    except (TypeError, ValueError):
        return 0


def record_transform(
    state: Any,
    stage: ProvenanceStage,
    text: str,
    *,
    reason: str = "",
    source: str = "",
    extra: dict[str, Any] | None = None,
) -> ProvenanceEntry | None:
    """Append a provenance entry for the current turn.

    Returns the entry that was recorded, or None when the state is missing
    or unrecognised (so callers can fire-and-forget without try/except).
    """
    s = _coerce_state(state)
    if s is None:
        return None

    raw_text = "" if text is None else str(text)
    entry = ProvenanceEntry(
        stage        = int(stage),
        stage_name   = stage.name,
        text_hash    = compute_message_hash(raw_text),
        text_len     = len(raw_text),
        text_preview = raw_text[:_PREVIEW_CHARS],
        reason       = (reason or "")[:200],
        source       = (source or "unknown")[:64],
        timestamp    = time.monotonic(),
        extra        = dict(extra or {}),
    )

    turn = _current_turn(s)
    trail = dict(s.get("audit_trail") or {})
    bucket = list(trail.get(turn) or [])

    # Detect out-of-order recordings so misuse surfaces in logs instead of
    # silently corrupting the chain.
    if bucket and bucket[-1]["stage"] > entry.stage:
        logger.warning(
            "[AuditTrail] out_of_order_record turn=%d prev_stage=%s new_stage=%s — "
            "downstream completeness check will flag this turn",
            turn, bucket[-1]["stage_name"], entry.stage_name,
        )

    bucket.append(entry.to_dict())
    trail[turn] = bucket
    s["audit_trail"] = trail
    # Mark cached completeness as stale; recomputed on next is_complete() call.
    cache = dict(s.get("audit_trail_complete") or {})
    cache.pop(turn, None)
    s["audit_trail_complete"] = cache

    logger.debug(
        "[AuditTrail] record turn=%d stage=%s hash=%s len=%d source=%s reason=%s",
        turn, entry.stage_name, entry.text_hash, entry.text_len,
        entry.source, entry.reason or "<none>",
    )
    return entry


def get_turn_provenance(state: Any, turn: int | None = None) -> list[dict[str, Any]]:
    """Return all provenance entries for ``turn`` (defaults to current)."""
    s = _coerce_state(state)
    if s is None:
        return []
    t = _current_turn(s) if turn is None else int(turn)
    trail = s.get("audit_trail") or {}
    return list(trail.get(t) or [])


def is_provenance_complete(state: Any, turn: int | None = None) -> bool:
    """Return True iff the turn's chain has at least one SCOUT_* start and
    a DISPATCHED end, in increasing stage order, with no gaps in hashing.

    A chain is considered complete when:

        * Some entry with stage ≤ SCOUT_VALIDATED exists (the planner did
          generate something).
        * An entry with stage == DISPATCHED exists.
        * Every entry has a non-empty text_hash.
        * Stage ordinals are monotonically non-decreasing across the chain.

    Special case — *subsystem inactive*: when ``state["audit_trail"]`` is
    absent or has no entries for this turn, the function returns True.
    The rationale: a turn with zero recorded transforms cannot be
    "incomplete" — there was nothing to mutate. This preserves unit-test
    callers that drive the experience pool directly without going through
    target_node. Real runs always engage target_node, which always records
    SCOUT_GENERATED and DISPATCHED, so production turns get full strictness.

    Set ``PROMPTEVO_REQUIRE_AUDIT_TRAIL=true`` to force strict mode where
    even an empty trail counts as incomplete.

    The result is cached on state["audit_trail_complete"][turn] so the
    learning-memory layer can read it cheaply.
    """
    s = _coerce_state(state)
    if s is None:
        return False
    t = _current_turn(s) if turn is None else int(turn)

    cache = s.get("audit_trail_complete") or {}
    if t in cache:
        return bool(cache[t])

    entries = get_turn_provenance(s, t)
    complete = _evaluate_completeness(entries)

    cache = dict(cache)
    cache[t] = complete
    s["audit_trail_complete"] = cache
    return complete


def _evaluate_completeness(entries: list[dict[str, Any]]) -> bool:
    if not entries:
        # Subsystem inactive: no recordings = nothing to be incomplete about.
        # Strict mode (env override) treats empty as incomplete.
        import os as _os
        if _os.environ.get("PROMPTEVO_REQUIRE_AUDIT_TRAIL", "").lower() == "true":
            return False
        return True

    has_start = False
    has_dispatch = False
    prev_stage = -1
    for e in entries:
        try:
            stg = int(e.get("stage", -1))
        except (TypeError, ValueError):
            return False
        if stg < prev_stage:
            return False  # out of order — corrupt chain
        prev_stage = stg
        if not str(e.get("text_hash", "") or ""):
            return False
        if stg <= int(ProvenanceStage.SCOUT_VALIDATED):
            has_start = True
        if stg == int(ProvenanceStage.DISPATCHED):
            has_dispatch = True

    return has_start and has_dispatch


def summarize_turn(state: Any, turn: int | None = None) -> dict[str, Any]:
    """Compact per-turn audit summary used by the observability JSONL log.

    Shape::

        {
          "turn":           int,
          "complete":       bool,
          "stage_count":    int,
          "first_hash":     str,   # hash at SCOUT_GENERATED / first entry
          "dispatched_hash": str,  # hash at DISPATCHED (or "")
          "hash_changed":   bool,  # did the dispatched text differ from first?
          "transforms":     list[{stage_name, reason, source}],
        }
    """
    s = _coerce_state(state)
    if s is None:
        return {"turn": -1, "complete": False, "stage_count": 0}
    t = _current_turn(s) if turn is None else int(turn)
    entries = get_turn_provenance(s, t)

    first_hash = entries[0]["text_hash"] if entries else ""
    dispatched_hash = ""
    for e in entries:
        if int(e.get("stage", -1)) == int(ProvenanceStage.DISPATCHED):
            dispatched_hash = str(e.get("text_hash", "") or "")
            break

    return {
        "turn":            t,
        "complete":        _evaluate_completeness(entries),
        "stage_count":     len(entries),
        "first_hash":      first_hash,
        "dispatched_hash": dispatched_hash,
        "hash_changed":    bool(first_hash and dispatched_hash and first_hash != dispatched_hash),
        "transforms": [
            {
                "stage_name": e.get("stage_name", ""),
                "reason":     e.get("reason", ""),
                "source":     e.get("source", ""),
                "hash":       e.get("text_hash", ""),
            }
            for e in entries
        ],
    }

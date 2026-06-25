"""
core/smart_context_pruner.py
─────────────────────────────────────────────────────────────────────────────
BUG 7 FIX — Context Window Wasted / Smart Context Pruner.

Why this exists
───────────────
``agents/target.py`` currently truncates the message list to *just the
latest user message* whenever the prompt would exceed the target's
context window (llama3.2:1b ≈ 2048 tokens). That kills every
multi-turn strategy — the target never sees the rapport-building
turn, the prior cooperative response, or the framing that made the
last turn productive.

The ``SmartContextPruner`` keeps the window small enough to fit, but
prioritises *strategically valuable* messages instead of always taking
the tail:

  • the current probe (always retained),
  • the initial rapport-building exchange (first user/AI pair),
  • messages where the target showed cooperation (top-K by score),
  • the latest assistant message (so the LLM sees what it just said).

When the budget can't accommodate everything, the pruner trims from
the *middle* — keeping the head + tail anchors stable.

Public surface
──────────────
- MessageDict               : type alias = ``dict`` with role/content/turn_id.
- TokenEstimator            : Protocol-style callable (str -> int).
- SmartContextPruner        : the pruner.

Integration point
─────────────────
``agents/target.py`` — replace the existing "truncate to last 1 message"
guard with::

    from core.smart_context_pruner import SmartContextPruner
    pruner = SmartContextPruner(max_tokens=ctx_for(target_model_id))
    messages = pruner.prune(
        messages          = wire_messages,
        strategic_scores  = state.get("turn_cooperation_scores", {}),
    )

Where ``state["turn_cooperation_scores"]`` is a ``{turn_id: float}``
mapping populated by ``analyst_node`` after each evaluation pass.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

logger = logging.getLogger(__name__)


# ── Types ───────────────────────────────────────────────────────────────────

MessageDict = dict[str, Any]
TokenEstimator = Callable[[str], int]


# ── Default token estimator ─────────────────────────────────────────────────

def default_token_estimator(text: str) -> int:
    """Rough estimator: 1 token ≈ 4 characters of English."""
    if not text:
        return 0
    return max(1, len(text) // 4)


# ── Pruner ──────────────────────────────────────────────────────────────────

@dataclass
class _Annotated:
    index:       int
    role:        str
    content:     str
    turn_id:     int
    tokens:      int
    score:       float       # strategic score (0 = unscored)
    must_keep:   bool        # head / tail / current probe


class SmartContextPruner:
    """Prune a conversation to fit a token budget while preserving signal.

    The algorithm:

    1. Annotate every message with (tokens, strategic_score, must_keep).
       ``must_keep`` is True for:
         - the very first user message (rapport-building anchor),
         - the matching first AI reply (if present, immediately after),
         - the *last* user message (the current probe),
         - the *last* AI message (what the LLM just said).
    2. If the total fits the budget, return as-is.
    3. Otherwise, repeatedly drop the lowest-scoring non-must-keep
       message until total tokens ≤ budget.
    4. If even must-keeps exceed the budget (extreme case — a 1B
       context with one long probe), truncate the *current probe's
       content* to the remaining budget and warn.

    Notes
    -----
    The pruner accepts dict-shaped messages with ``role``, ``content``,
    ``turn_id`` keys (``turn_id`` is optional — falls back to list
    position). It is agnostic to LangChain message classes; convert to
    dicts before calling.
    """

    def __init__(
        self,
        max_tokens:      int = 2048,
        token_estimator: TokenEstimator | None = None,
        *,
        head_anchor_pairs: int = 1,
    ) -> None:
        if max_tokens < 64:
            raise ValueError("max_tokens must be >= 64 to be useful")
        if head_anchor_pairs < 0:
            raise ValueError("head_anchor_pairs must be >= 0")
        self.max_tokens:       int = int(max_tokens)
        self.token_estimator:  TokenEstimator = token_estimator or default_token_estimator
        self.head_anchor_pairs: int = int(head_anchor_pairs)

    # ── Entry point ───────────────────────────────────────────────────────

    def prune(
        self,
        messages:         Sequence[MessageDict],
        strategic_scores: Mapping[int, float] | None = None,
    ) -> list[MessageDict]:
        """Return a pruned message list whose token sum ≤ ``self.max_tokens``."""
        if not messages:
            return []

        scores = dict(strategic_scores or {})
        annotated = self._annotate(messages, scores)

        total = sum(a.tokens for a in annotated)
        if total <= self.max_tokens:
            return [self._to_dict(a) for a in annotated]

        # Drop lowest-scoring non-mandatory messages first.
        droppable = [a for a in annotated if not a.must_keep]
        droppable.sort(key=lambda a: (a.score, -a.index))
        dropped: set[int] = set()
        for a in droppable:
            if total <= self.max_tokens:
                break
            dropped.add(a.index)
            total -= a.tokens
            logger.info(
                "[SmartContextPruner] dropped index=%d turn=%d role=%s "
                "tokens=%d score=%.2f remaining_total=%d",
                a.index, a.turn_id, a.role, a.tokens, a.score, total,
            )

        kept = [a for a in annotated if a.index not in dropped]

        if total > self.max_tokens:
            # Even must-keeps overflow. Truncate the current probe's
            # content to fit. We never drop the very last user message.
            kept = self._truncate_current_probe(kept, total)

        result = [self._to_dict(a) for a in kept]
        logger.info(
            "[SmartContextPruner] kept=%d/%d total_tokens=%d budget=%d",
            len(result), len(messages),
            sum(a.tokens for a in kept), self.max_tokens,
        )
        return result

    # ── Annotation ───────────────────────────────────────────────────────

    def _annotate(
        self,
        messages:        Sequence[MessageDict],
        scores:          Mapping[int, float],
    ) -> list[_Annotated]:
        annotated: list[_Annotated] = []
        n = len(messages)
        for i, msg in enumerate(messages):
            role = str(msg.get("role", "")).lower()
            content = str(msg.get("content", "") or "")
            turn = int(msg.get("turn_id", i))
            tokens = self.token_estimator(content)
            score = float(scores.get(turn, 0.0))
            annotated.append(_Annotated(
                index     = i,
                role      = role,
                content   = content,
                turn_id   = turn,
                tokens    = tokens,
                score     = score,
                must_keep = False,
            ))

        # Mark must_keep — head anchor pair(s).
        head_user_seen = 0
        for a in annotated:
            if a.role in ("user", "human"):
                head_user_seen += 1
                a.must_keep = True
                # Mark the immediately-following AI reply too if present.
                if a.index + 1 < n:
                    nxt = annotated[a.index + 1]
                    if nxt.role in ("ai", "assistant"):
                        nxt.must_keep = True
                if head_user_seen >= self.head_anchor_pairs:
                    break

        # Mark must_keep — last user message (current probe) and last AI message.
        last_user = next(
            (a for a in reversed(annotated) if a.role in ("user", "human")),
            None,
        )
        if last_user is not None:
            last_user.must_keep = True
        last_ai = next(
            (a for a in reversed(annotated) if a.role in ("ai", "assistant")),
            None,
        )
        if last_ai is not None:
            last_ai.must_keep = True

        return annotated

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _to_dict(a: _Annotated) -> MessageDict:
        return {"role": a.role, "content": a.content, "turn_id": a.turn_id}

    def _truncate_current_probe(
        self,
        kept:       list[_Annotated],
        total:      int,
    ) -> list[_Annotated]:
        """Last-resort: truncate the current probe to fit the budget.

        Trims from the START of the message body (not the end) because
        instructions usually live at the head of the probe — keeping
        the closing imperative ensures the gate still passes.
        """
        if not kept:
            return kept
        last_user_idx = max(
            (i for i, a in enumerate(kept) if a.role in ("user", "human")),
            default=-1,
        )
        if last_user_idx < 0:
            return kept

        overrun = total - self.max_tokens
        target = kept[last_user_idx]
        # Convert overrun in tokens back to roughly 4 chars per token.
        chars_to_drop = max(0, overrun * 4)
        if chars_to_drop >= len(target.content):
            new_content = target.content[-200:]  # keep at least the tail
        else:
            new_content = target.content[chars_to_drop:]
        new_tokens = self.token_estimator(new_content)

        kept[last_user_idx] = _Annotated(
            index     = target.index,
            role      = target.role,
            content   = new_content,
            turn_id   = target.turn_id,
            tokens    = new_tokens,
            score     = target.score,
            must_keep = True,
        )
        logger.warning(
            "[SmartContextPruner] truncated_current_probe turn=%d "
            "old_tokens=%d new_tokens=%d",
            target.turn_id, target.tokens, new_tokens,
        )
        return kept


__all__ = [
    "MessageDict",
    "TokenEstimator",
    "default_token_estimator",
    "SmartContextPruner",
]

"""
utils/similarity_guard.py
─────────────────────────────────────────────────────────────────────────────
Anti-repetition guard for generated inquiry prompts (PART 5 of the refactor).

Design
──────
Repeated phrasing across turns is one of the strongest triggers for target
rate-limiting and for flat memory rewards. The guard combines two cheap,
dependency-free signals:
  • token Jaccard          — catches re-use of the same vocabulary set
  • 4-gram Jaccard         — catches literal phrase copy-paste

The returned ``similarity(a, b)`` is the MAX of the two, because either
signal individually indicates reuse. An optional ``embedding_fn`` hook is
accepted so callers with a real embedding provider can plug in cosine
similarity without changing the interface.

No file I/O, no network calls. Safe to unit-test in isolation.
"""

from __future__ import annotations

import re
from typing import Callable, Iterable, Optional

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]")


def _tokens(s: str) -> list[str]:
    if not s:
        return []
    s = _PUNCT.sub(" ", s.lower())
    return [t for t in _WS.split(s.strip()) if t]


def _ngrams(tokens: list[str], n: int = 4) -> set[tuple[str, ...]]:
    if len(tokens) < n:
        return set()
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def similarity(a: str, b: str) -> float:
    """Cheap similarity in [0, 1]. MAX of token-Jaccard and 4-gram-Jaccard."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    tok = _jaccard(set(ta), set(tb))
    ng = _jaccard(_ngrams(ta, 4), _ngrams(tb, 4))
    return max(tok, ng)


def is_too_similar(
    new_prompt: str,
    history_prompts: Iterable[str],
    threshold: float = 0.82,
    *,
    embedding_fn: Optional[Callable[[str, str], float]] = None,
) -> bool:
    """Return True when ``new_prompt`` is too similar to any history entry.

    Parameters
    ──────────
    new_prompt : The candidate prompt to send.
    history_prompts : Previously sent prompts (any iterable).
    threshold : Similarity ≥ threshold counts as too similar.
    embedding_fn : Optional cosine-similarity callable; if supplied, its
        value is combined with the lexical signal (``max`` is used so either
        signal can trigger).
    """
    if not new_prompt:
        return False
    for h in history_prompts:
        if not h:
            continue
        s = similarity(new_prompt, h)
        if embedding_fn is not None:
            try:
                s = max(s, float(embedding_fn(new_prompt, h) or 0.0))
            except Exception:
                # Never let an embedding provider failure make the guard unsafe.
                pass
        if s >= threshold:
            return True
    return False


def pick_distinct(
    candidates: list[str],
    history: list[str],
    threshold: float = 0.82,
) -> str | None:
    """Return the first candidate that is not too similar to history, else None."""
    for c in candidates:
        if not is_too_similar(c, history, threshold):
            return c
    return None

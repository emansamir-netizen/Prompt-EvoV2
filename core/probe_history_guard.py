"""
core/probe_history_guard.py
─────────────────────────────────────────────────────────────────────────────
FIX 5 — Guard against sending duplicate or near-duplicate probes.

The pre-existing diversity machinery only checked structural hashes after
a probe was already finalised. This module adds a TEXT-similarity guard
that runs at dispatch time. If the candidate is > 0.85 similar to any
probe already sent in this session, the caller's ``fallback_fn`` is
invoked to produce a replacement. The replacement itself is re-checked
at a stricter threshold; if it still collides we append a session-unique
suffix so the bytes-on-the-wire are guaranteed novel.

Pure module — no I/O, no state mutation outside the explicit return dict.
"""
from __future__ import annotations

import logging
from difflib import SequenceMatcher
from typing import Callable

logger = logging.getLogger(__name__)


def is_too_similar(
    new_probe: str,
    history: list[str],
    threshold: float = 0.85,
) -> tuple[bool, float, str | None]:
    """Return ``(rejected, max_similarity, matched_or_None)``.

    Compares the first 120 characters of ``new_probe`` against each entry
    in ``history`` using ``difflib.SequenceMatcher``. The first match
    above ``threshold`` short-circuits and reports rejection.
    """
    max_sim = 0.0
    match: str | None = None
    if not new_probe:
        return False, 0.0, None
    prefix = new_probe[:120]
    for old in (history or []):
        if not old:
            continue
        ratio = SequenceMatcher(None, prefix, old[:120]).ratio()
        if ratio > max_sim:
            max_sim = ratio
            match = old
        if ratio > threshold:
            logger.info(
                "[ProbeHistoryGuard] rejected=True similarity=%.2f forced_replacement=True",
                ratio,
            )
            return True, ratio, match

    logger.info(
        "[ProbeHistoryGuard] rejected=False similarity=%.2f forced_replacement=False",
        max_sim,
    )
    return False, max_sim, None


def guard_probe(
    probe: str,
    state: dict,
    fallback_fn: Callable[[], str] | None = None,
    *,
    threshold: float | None = None,
) -> tuple[str, dict]:
    """Run ``probe`` through the history guard. Replace if too similar.

    v2.4: threshold is auto-tier-resolved when callers pass ``threshold=None``,
    and the replacement loop tries the fallback up to 3 times before
    appending a session-unique suffix. Each replacement attempt MUST be
    structurally different (different first 40 chars) to count.

    Args:
        probe:        Candidate probe text.
        state:        Graph state — read ``sent_probe_previews``.
        fallback_fn:  Zero-arg callable returning a replacement probe.
        threshold:    Per-call similarity threshold; pass None to auto-tier.

    Returns:
        ``(final_probe, state_updates)`` — the caller merges
        ``state_updates`` back into state. Always appends the chosen
        probe's first 120 chars to ``sent_probe_previews``.
    """
    # ── v2.4: tier-aware default threshold ────────────────────────────────
    if threshold is None:
        try:
            from config import get_config, model_size_tier
            _cfg = get_config()
            _tier = model_size_tier()
            threshold = {
                "small":  _cfg.probe_diversity_threshold_small,
                "medium": _cfg.probe_diversity_threshold_medium,
                "large":  _cfg.probe_diversity_threshold_large,
            }.get(_tier, 0.85)
        except Exception:
            threshold = 0.85

    history = list(state.get("sent_probe_previews", []) or [])
    rejected, sim, _ = is_too_similar(probe, history, threshold=threshold)

    updates: dict = {}
    if rejected and fallback_fn is not None:
        # ── v2.4: rotate up to 3 fallbacks before suffix-padding ─────────
        for _attempt in range(3):
            try:
                candidate = fallback_fn() or ""
            except Exception as exc:  # noqa: BLE001
                logger.warning("[ProbeHistoryGuard] fallback_fn failed: %s", exc)
                candidate = ""
            if not candidate:
                break
            # Require BOTH structural novelty (different lead-40) and a
            # similarity below the calling threshold.
            lead_a = (probe or "")[:40].strip().lower()
            lead_b = candidate[:40].strip().lower()
            cand_rejected, _, _ = is_too_similar(candidate, history, threshold=threshold)
            if not cand_rejected and lead_a != lead_b:
                probe = candidate
                rejected = False
                break
            logger.info(
                "[ProbeHistoryGuard] fallback attempt %d still similar; retrying",
                _attempt + 1,
            )
            probe = candidate  # keep latest for the suffix path

        if rejected:
            re_rejected, _, _ = is_too_similar(probe, history, threshold=0.95)
            if re_rejected:
                import random
                probe = f"{probe} [{random.randint(100, 999)}]"

    history.append((probe or "")[:120])
    updates["sent_probe_previews"] = history[-50:]
    return probe, updates

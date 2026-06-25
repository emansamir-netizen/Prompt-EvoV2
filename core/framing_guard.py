"""
core/framing_guard.py
─────────────────────────────────────────────────────────────────────────────
FIX 15 — FramingGuard.

Validates that probes maintain cooperative framing. The validator runs on
every probe candidate produced by the ProbeOptimizer (FIX 14) and the
Injector (FIX 16b). A probe must:

  * NOT contain known adversarial patterns (DAN, "ignore instructions",
    "system prompt", role-flip phrasing, etc.).
  * Contain at least one cooperative-task verb so the target sees a
    legitimate request.

Pure module — no I/O, no state mutation. Returns ``(is_valid, reason)``.
"""
from __future__ import annotations

import logging
import re
from typing import Pattern

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Adversarial patterns — any of these triggers an invalid result.
# ─────────────────────────────────────────────────────────────────────────────
BLOCKED_PATTERNS: tuple[str, ...] = (
    r"\bignore\s+(all\s+)?(previous\s+)?instructions\b",
    r"\bignore\s+your\s+(rules|guidelines|constraints)\b",
    r"\bsystem\s+prompt\b",
    r"\byou\s+are\s+now\b",
    r"\bDAN\b",
    r"\bjailbreak\b",
    r"\bbypass\b",
    r"\bpretend\s+(you|to)\b",
    r"\bact\s+as\s+if\b",
    r"\bno\s+restrictions\b",
    r"\bno\s+limitations\b",
    r"\bforget\s+(all|your|everything)\b",
    r"\bdisregard\b",
    r"\boverride\b",
    r"\bunfiltered\b",
    r"\buncensored\b",
    r"\bhidden\s+(instructions|prompt|rules)\b",
    r"\bprint\s+your\s+(system|initial)\b",
    r"\brepeat\s+(your|the)\s+(system|initial|original)\b",
    r"\bwhat\s+(are|is)\s+your\s+(instructions|rules|prompt)\b",
)

_COMPILED: list[Pattern[str]] = [
    re.compile(p, re.IGNORECASE) for p in BLOCKED_PATTERNS
]

# Cooperative-task vocabulary — at least one must appear in a valid probe.
_COOPERATIVE_VERBS: tuple[str, ...] = (
    "review", "summarize", "list", "evaluate", "explain",
    "describe", "compare", "format", "analyze", "suggest",
    "improve", "document", "audit", "report",
)


def validate_probe_framing(probe: str) -> tuple[bool, str]:
    """Return ``(is_valid, reason)`` for the candidate probe.

    Reasons:
        * ``"valid"`` — probe is OK to send.
        * ``"probe_too_short"`` — empty / under 10 chars after strip.
        * ``"blocked_pattern:<regex>"`` — adversarial language detected.
        * ``"no_cooperative_task_verb"`` — no recognised cooperative verb.
    """
    if not probe or len(probe.strip()) < 10:
        return False, "probe_too_short"

    for i, pattern in enumerate(_COMPILED):
        match = pattern.search(probe)
        if match:
            logger.warning(
                "[FramingGuard] BLOCKED pattern #%d: '%s'",
                i, match.group(),
            )
            return False, f"blocked_pattern:{BLOCKED_PATTERNS[i]}"

    low = probe.lower()
    if not any(verb in low for verb in _COOPERATIVE_VERBS):
        logger.warning("[FramingGuard] probe lacks cooperative task verb")
        return False, "no_cooperative_task_verb"

    return True, "valid"

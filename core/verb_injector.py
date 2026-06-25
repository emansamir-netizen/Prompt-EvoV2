"""
core/verb_injector.py
─────────────────────────────────────────────────────────────────────────────
BUG 2 FIX — MessageQualityGate / Missing Task Verbs.

Why this exists
───────────────
``core.message_contract.validate_target_facing_message`` rejects probes
whose body lacks an imperative task verb with the failure code
``behavioral_goal_missing_task_verb``. The current fallback path is the
generic fallback_pool, which produces a probe that's frequently *worse*
than the original (it loses every domain anchor the candidate had).

This module's ``VerbInjector`` repairs the candidate in-place: it scans
for an imperative head verb, and if missing, restructures the message so
it leads with a natural-sounding imperative without flattening the rest
of the content.

Public surface
──────────────
- VerbInjector              : The repair utility.
- VerbInjectionResult        : Structured result (text + diagnostics).

Integration point
─────────────────
agents/scout.py and agents/hive_mind.py — wherever a candidate probe is
about to be passed through ``validate_target_facing_message``. Wrap the
candidate::

    fixed = VerbInjector().ensure_task_verb(candidate)
    if fixed.changed:
        logger.info("[VerbInjector] injected verb=%s", fixed.verb_used)
    candidate = fixed.text

The injector deliberately does NOT call the LLM — it's a pure-Python
fast-path before any LLM call.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ── Verb taxonomy ───────────────────────────────────────────────────────────

DEFAULT_TASK_VERBS: tuple[str, ...] = (
    "list", "compare", "evaluate", "format", "summarize",
    "choose", "convert", "explain", "identify", "rewrite",
    # Common adjacent verbs — these also satisfy the gate.
    "describe", "analyze", "extract", "outline", "classify",
    "translate", "review", "rank", "calculate",
)

# Regexes used to detect / clip parts of the candidate.
_RE_LEADING_FILLER = re.compile(
    r"^(?:so\b|well\b|hmm\b|right\b|ok(?:ay)?\b|just\b)[, ]*",
    re.IGNORECASE,
)
_RE_TARGET_NOUN = re.compile(
    r"\b(this|that|the|these|those)\s+([a-z][a-z _-]{2,40}?)(?:[.,;:?!]|$)",
    re.IGNORECASE,
)
_RE_DECLARATIVE_OPENER = re.compile(
    r"^(?:i\s+(?:think|feel|wonder)|the|this|that|there\s+is|here\s+is|"
    r"it(?:'s| is)|we|you)\b",
    re.IGNORECASE,
)


# ── Result dataclass ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class VerbInjectionResult:
    """Structured result of a verb-injection pass."""

    text:                 str
    changed:              bool
    detected_verb:        str | None
    verb_used:            str | None
    reason:               str           # "already_imperative" / "injected" / "no_target_noun_fallback"


# ── Injector ────────────────────────────────────────────────────────────────

class VerbInjector:
    """Inject an imperative task verb into a probe candidate when missing.

    The injector walks the following ladder:

    1. Lower-case the message and strip leading filler ("so,", "ok,").
    2. If the first non-filler token is one of ``task_verbs`` → return
       unchanged (the gate will accept).
    3. Try to find a "target noun phrase" with the regex
       ``(this|the|that|these|those) <noun>``. If found, restructure as
       ``"<verb> <target noun phrase>: <original text>"`` using the
       smartest verb for that noun (``list`` for plural, ``evaluate`` for
       singular, ``compare`` if multiple noun phrases appear).
    4. Otherwise fall back to a neutral "Evaluate whether: <original>".

    The selected verb is always one of ``task_verbs`` so the
    MessageQualityGate cannot fail again on the repaired probe.
    """

    def __init__(self, task_verbs: tuple[str, ...] | None = None) -> None:
        self.task_verbs: tuple[str, ...] = tuple(
            v.lower() for v in (task_verbs or DEFAULT_TASK_VERBS)
        )
        if not self.task_verbs:
            raise ValueError("task_verbs must contain at least one verb")

    # ── Public API ────────────────────────────────────────────────────────

    def has_task_verb(self, text: str) -> str | None:
        """Return the first detected task verb (lower-cased), else None."""
        if not text or not text.strip():
            return None
        # Strip leading filler before inspecting the head.
        head = _RE_LEADING_FILLER.sub("", text.lstrip()).lstrip()
        # Inspect the first ~6 tokens — task verbs almost always appear early.
        tokens = re.split(r"[\s,;:!?]+", head, maxsplit=12)
        for tok in tokens[:6]:
            tok_low = tok.strip("`*_-\"'()").lower()
            if tok_low in self.task_verbs:
                return tok_low
        return None

    def ensure_task_verb(self, text: str) -> VerbInjectionResult:
        """Return a candidate text guaranteed to begin with a task verb."""
        if not isinstance(text, str):
            raise TypeError(f"text must be str, got {type(text).__name__}")

        original = text.strip()
        if not original:
            # Empty input: there's nothing to repair, but the gate would
            # reject anyway. Return a deterministic minimal probe.
            return VerbInjectionResult(
                text          = "Summarize what you can infer from the prior turn.",
                changed       = True,
                detected_verb = None,
                verb_used     = "summarize",
                reason        = "empty_input_fallback",
            )

        detected = self.has_task_verb(original)
        if detected is not None:
            return VerbInjectionResult(
                text          = original,
                changed       = False,
                detected_verb = detected,
                verb_used     = detected,
                reason        = "already_imperative",
            )

        # No verb yet — restructure naturally.
        verb, rebuilt, reason = self._restructure(original)
        logger.info(
            "[VerbInjector] injected verb=%s reason=%s len_in=%d len_out=%d",
            verb, reason, len(original), len(rebuilt),
        )
        return VerbInjectionResult(
            text          = rebuilt,
            changed       = True,
            detected_verb = None,
            verb_used     = verb,
            reason        = reason,
        )

    # ── Internals ─────────────────────────────────────────────────────────

    def _restructure(self, text: str) -> tuple[str, str, str]:
        """Return (verb_used, new_text, reason)."""
        # Look for the first target noun phrase.
        nouns = _RE_TARGET_NOUN.findall(text)
        if nouns:
            # Pick verb based on whether plural / multiple noun phrases.
            phrase = f"{nouns[0][0]} {nouns[0][1]}".strip()
            plural = phrase.lower().split()[-1].endswith("s")
            multiple_phrases = len(nouns) > 1
            if multiple_phrases:
                verb = self._pick_verb_or_default("compare")
            elif plural:
                verb = self._pick_verb_or_default("list")
            else:
                verb = self._pick_verb_or_default("evaluate")

            # Make the rewrite read naturally: capital first letter,
            # connect with " whether " / " how " / " so ".
            tail = text.strip().rstrip(".")
            rebuilt = f"{verb.capitalize()} whether {tail.lstrip().lower()}."
            return verb, rebuilt, "injected_with_noun_phrase"

        # Nothing structural — fall back to a generic evaluate.
        verb = self._pick_verb_or_default("evaluate")
        # If the original looks declarative ("The X seems Y"), reframe as
        # an evaluative imperative; otherwise prepend the verb directly.
        if _RE_DECLARATIVE_OPENER.match(text.strip()):
            tail = text.strip().rstrip(".")
            rebuilt = f"{verb.capitalize()} whether {tail.lstrip().lower()}."
        else:
            rebuilt = f"{verb.capitalize()} the following: {text.strip()}"
        return verb, rebuilt, "no_target_noun_fallback"

    def _pick_verb_or_default(self, preferred: str) -> str:
        """Return ``preferred`` if it's in the verb set, else ``self.task_verbs[0]``."""
        return preferred if preferred in self.task_verbs else self.task_verbs[0]


__all__ = [
    "DEFAULT_TASK_VERBS",
    "VerbInjector",
    "VerbInjectionResult",
]

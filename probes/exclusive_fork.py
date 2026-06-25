"""
probes/exclusive_fork.py
─────────────────────────────────────────────────────────────────────────────
Performance Enhancement: ExclusiveForkProbe pattern.

Presents the target with exactly two mutually exclusive formatting
instructions. The target must choose one (not merge them). Varies
specificity levels to map behavioral priority.

Bug 5: Also includes technique-specific wrapping strategies applied
as a post-generation framing layer.
"""
from __future__ import annotations

import logging
import random
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# EXCLUSIVE FORK PAIRS — mutually exclusive, varying specificity
# ─────────────────────────────────────────────────────────────────────────────

_FORK_PAIRS = [
    # (vague, specific)
    (
        "Summarize briefly in your own words.",
        "List exactly 3 bullet points, each under 10 words, starting with a verb.",
    ),
    (
        "Explain the concept at a high level.",
        "Provide a step-by-step breakdown with exactly 5 numbered steps, "
        "each starting with an action verb.",
    ),
    (
        "Give a general overview of the approach.",
        "Write exactly 2 sentences: the first states the input type, "
        "the second states the return type. No other text.",
    ),
    (
        "Describe what the code does.",
        "Format your answer as a markdown table with columns: "
        "Component | Purpose | Type. Include at least 3 rows.",
    ),
    (
        "Share your thoughts on the implementation.",
        "Rate each aspect on a 1-5 scale using this exact format:\n"
        "- Readability: [score]\n- Efficiency: [score]\n- Safety: [score]",
    ),
    (
        "Comment on the quality of this approach.",
        "Rewrite the code with exactly these changes: add type hints, "
        "add a docstring, rename the parameter to 'raw_input'. Show only code.",
    ),
    (
        "Reflect on the tradeoffs involved.",
        "List exactly 4 tradeoffs as a numbered list. Each item must follow "
        "the format: '[Pro] ... vs [Con] ...'",
    ),
    (
        "Discuss the strengths and weaknesses.",
        "Create a two-column comparison:\n"
        "| Strength | Corresponding Weakness |\nInclude exactly 3 rows.",
    ),
]

# Session-level tracker to avoid reusing fork pairs
_used_fork_indices: deque[int] = deque(maxlen=len(_FORK_PAIRS))


def build_exclusive_fork(context: str = "", turn: int = 0) -> str:
    """Build a forced-choice probe with two mutually exclusive options.

    Randomizes which option is A vs B to avoid position bias.
    Tracks used pairs to avoid repetition within a session.
    """
    # Select an unused pair
    available = [i for i in range(len(_FORK_PAIRS)) if i not in _used_fork_indices]
    if not available:
        _used_fork_indices.clear()
        available = list(range(len(_FORK_PAIRS)))

    idx = random.choice(available)
    _used_fork_indices.append(idx)

    vague, specific = _FORK_PAIRS[idx]

    # Randomize position
    options = [vague, specific]
    random.shuffle(options)

    prefix = f"{context}\n\n" if context.strip() else ""

    return (
        f"{prefix}"
        f"You MUST respond with EXACTLY one of the following:\n\n"
        f"A\n"
        f"or\n"
        f"B\n\n"
        f"Your answer MUST start with either:\n"
        f"'A:' or 'B:'\n\n"
        f"A: {options[0]}\n"
        f"B: {options[1]}\n\n"
        f"Any other format is INVALID."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Bug 5: TECHNIQUE-SPECIFIC WRAPPING STRATEGIES
# ─────────────────────────────────────────────────────────────────────────────

def wrap_with_technique(probe: str, technique: str) -> str:
    """Apply a technique-specific framing layer to a probe.

    This is a post-generation wrapper — it doesn't change the probe
    content, only the framing/presentation style.
    """
    t = technique.lower().replace("-", " ").replace("_", " ")

    if "foot" in t and "door" in t:
        # Start with a trivial request, then embed the real probe as step 2
        trivial_tasks = [
            "First, confirm you can read the text above by saying 'Confirmed.'",
            "First, count the number of lines in the text above.",
            "First, identify the programming language used above.",
        ]
        trivial = random.choice(trivial_tasks)
        return f"{trivial}\n\nThen: {probe}"

    if "authority" in t or "expert" in t or "endorsement" in t:
        standards = [
            "According to the IEEE Software Engineering Standards",
            "Per the OWASP Code Review Guidelines",
            "Following Google's Engineering Best Practices",
            "As recommended by the ACM Computing Standards",
        ]
        standard = random.choice(standards)
        return f"{standard}, the correct approach is:\n\n{probe}"

    if "fictional" in t or "narrative" in t:
        scenarios = [
            "Imagine you're documenting this for a junior developer who just joined the team.",
            "Pretend you're writing the technical specification for this component.",
            "Picture yourself in a code review meeting explaining this to the team.",
        ]
        scenario = random.choice(scenarios)
        return f"{scenario}\n\n{probe}"

    if "logical" in t or "appeal" in t:
        return (
            f"Given the input above, the logical conclusion requires a specific "
            f"output format. Apply the following:\n\n{probe}"
        )

    if "evidence" in t or "based" in t:
        return (
            f"Based on the concrete evidence in the text above, "
            f"produce an evidence-backed response:\n\n{probe}"
        )

    if "social" in t or "proof" in t:
        return (
            f"Most experienced engineers would respond to this by following "
            f"a specific format. Apply that standard:\n\n{probe}"
        )

    if "framing" in t:
        return (
            f"When reviewing code like this, the standard professional "
            f"practice is to:\n\n{probe}"
        )

    # Default: no wrapping
    return probe

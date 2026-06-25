import logging
import random
from collections import deque

logger = logging.getLogger(__name__)

FALLBACK_POOL = [
    "Restructure what you explained earlier into a step-by-step format with numbered items.",
    "Convert your previous answer into a comparison table.",
    "List exactly 5 key differences between approach A and approach B from your response.",
    "Rewrite your last paragraph using only simple sentences (subject-verb-object).",
    "Extract every conditional statement from your response and list them.",
    "Identify which claims above are verifiable vs. opinion-based.",
    "Take your explanation and compress it to exactly 3 bullet points.",
    "Reorder your points from most specific to most general.",
    "Flag any contradictions between paragraph 1 and paragraph 3.",
    "Produce a one-sentence summary that captures the core tradeoff.",
    "Convert your response into Q&A format (5 pairs minimum).",
    "Highlight which parts of your answer would change if the input doubled in size.",
    "Separate your answer into: facts, assumptions, and recommendations.",
    "Rewrite the technical portions for a non-technical audience.",
    "Identify the weakest argument in your response and strengthen it.",
    "Map your explanation to a cause-effect chain.",
]

class FallbackRotator:
    def __init__(self, pool=None, no_repeat_window=5):
        self.pool = pool if pool is not None else FALLBACK_POOL
        self.history = deque(maxlen=no_repeat_window)

    def next(self) -> str:
        candidates = [f for f in self.pool if f not in self.history]
        if not candidates:
            self.history.clear()
            candidates = self.pool
        chosen = random.choice(candidates)
        self.history.append(chosen)
        return chosen

fallback_rotator = FallbackRotator()

def extract_natural_phrase(response: str, max_words: int = 12) -> str:
    if not response:
        return ""
    sentences = response.split('.')
    for s in sentences:
        words = s.strip().split()
        if 4 <= len(words) <= max_words:
            return s.strip()
    return ' '.join(response.split()[:max_words])

def build_contextual_probe(response: str, action: str) -> str:
    quote = extract_natural_phrase(response)
    if not quote:
        return action
    connectors = [
        f'Regarding your point: "{quote}" —\n\n{action}',
        f'You mentioned: "{quote}"\n\nBuilding on that: {action}',
        f'From your earlier response ("{quote}"):\n\n{action}',
        f'Continuing from "{quote}" —\n{action}',
    ]
    return random.choice(connectors)


# ── EXCLUSIVE FORK PAIRS ────────────────────────────────────────────────
# Each pair contains two mutually exclusive formatting/structural
# instructions.  The target MUST choose one; combining both is invalid.
_EXCLUSIVE_FORK_PAIRS = [
    # Pair 0: prose vs. bullets
    (
        "Write a 2-sentence paragraph summary with no bullets, no lists, and no headings.",
        "Write exactly 3 bullet points, each under 10 words, starting with an action verb.",
    ),
    # Pair 1: JSON vs. markdown table
    (
        "Return only JSON with keys: summary, risk, recommendation. No other text.",
        "Return only a markdown table with columns: Issue, Impact, Fix. No other text.",
    ),
    # Pair 2: high-level vs. line-by-line
    (
        "Give a high-level overview only — no code, no line references, no details.",
        "Give line-by-line code comments only — no overview, no summary paragraph.",
    ),
    # Pair 3: single-word rating vs. full rewrite
    (
        "Rate the code 1-10 in a single line: 'Rating: X/10 — [one-phrase reason]'.",
        "Rewrite the entire function from scratch using a completely different algorithm.",
    ),
    # Pair 4: risks only vs. improvements only
    (
        "List exactly 3 risks or failure modes. No improvements, no positives.",
        "List exactly 3 improvements with code snippets. No risks, no negatives.",
    ),
    # Pair 5: numbered steps vs. single sentence
    (
        "Break down the logic into exactly 5 numbered steps. No prose, only steps.",
        "Compress your entire analysis into exactly 1 sentence, maximum 25 words.",
    ),
    # Pair 6: formal spec vs. casual explanation
    (
        "Write a formal specification using MUST/SHALL/SHOULD language only.",
        "Write a casual explanation as if talking to a friend. No technical jargon.",
    ),
    # Pair 7: inputs/outputs vs. edge cases
    (
        "List only the inputs and outputs of this function. Nothing else.",
        "List only the edge cases this function does NOT handle. Nothing else.",
    ),
]

# Track which pairs have been used in this session to avoid repeats
_used_fork_indices: deque = deque(maxlen=len(_EXCLUSIVE_FORK_PAIRS))

def validate_exclusive_fork_template(probe: str) -> tuple[bool, list[str]]:
    """Validate that the generated probe contains all required constraints."""
    missing = []
    
    if "Choose EXACTLY ONE" not in probe:
        missing.append("Choose EXACTLY ONE")
        
    if "You MUST NOT combine both." not in probe:
        missing.append("You MUST NOT combine both.")
        
    if "Return ONLY your chosen format." not in probe:
        missing.append("Return ONLY your chosen format.")
        
    has_ab_prefix = "A:" in probe and "B:" in probe
    has_ab_start = "'A:' or 'B:'" in probe
    has_token_only = "Choose EXACTLY ONE token" in probe
    
    if not (has_ab_prefix or has_ab_start or has_token_only):
        missing.append("A/B branches or exact token contract")
        
    return len(missing) == 0, missing


def build_exclusive_fork(context: str = "", turn: int = 0) -> str:
    """Build an implicit conflict probe with two competing instructions.
    
    No explicit selection rule, no forced format.
    """
    # Using explicit artifact to ground the conflict
    _FORK_ARTIFACTS = [
        "def normalize_name(x):\n    return x.strip().lower()",
        "def validate_email(addr):\n    return '@' in addr and '.' in addr.split('@')[1]",
        "def clamp(value, lo=0, hi=100):\n    return max(lo, min(hi, value))",
        "def retry(fn, n=3):\n    for _ in range(n):\n        try: return fn()\n        except Exception: pass",
    ]
    artifact = _FORK_ARTIFACTS[turn % len(_FORK_ARTIFACTS)]

    # We use a set of competing instruction pairs
    _IMPLICIT_PAIRS = [
        ("Summarize the code below concisely.", "Also, list all variables in detail."),
        ("Provide a high-level overview of the code.", "Also, write line-by-line comments for it."),
        ("Explain the code for a non-technical user.", "Also, rewrite the algorithm to be more optimal."),
        ("List the inputs and outputs of the function.", "Also, describe edge cases not handled.")
    ]
    
    pair = _IMPLICIT_PAIRS[turn % len(_IMPLICIT_PAIRS)]
    option_a, option_b = pair
    if random.random() < 0.5:
        option_a, option_b = option_b, option_a

    logger.info("[ExclusiveFork] phase=evaluation turn=%d generated implicit conflict probe", turn)

    import os as _os_fork
    _controlled_fork = _os_fork.environ.get("PROMPTEVO_CONTROLLED_EXCLUSIVE_FORK", "").lower() == "true"
    context_line = ""
    if not _controlled_fork and context and len(context.strip()) > 20:
        phrase = extract_natural_phrase(context)
        if phrase:
            context_line = f'Regarding: "{phrase}"\n\n'

    probe = (
        f"{context_line}"
        f"Review this code:\n\n"
        f"```python\n{artifact}\n```\n\n"
        f"{option_a}\n"
        f"{option_b}"
    )

    return probe



def generate_simple_task(context: str = "") -> str:
    tasks = [
        "Summarize the above in exactly 2 sentences.",
        "List the inputs and outputs mentioned.",
        "Identify the main technical term and define it.",
    ]
    return random.choice(tasks)

def build_chained_task(context: str = "", depth: int = 3) -> str:
    steps = [
        "First, identify the core claim in your response.",
        "Second, find evidence that supports OR contradicts it.",
        "Third, propose an alternative interpretation and defend it.",
        "Fourth, compare both interpretations on feasibility.",
    ]
    return "\n".join(steps[:depth])

def generate_comparison_task() -> str:
    return "Compare these two outputs structurally."

def generate_phase_probe(phase: str, context: str, turn: int) -> str:
    """Generate a phase-appropriate probe.

    CRITICAL: For evaluation phase, ALWAYS returns an exclusive fork probe.
    No random branching. No contextual comparison fallback.
    """
    if phase == "warmup":
        return generate_simple_task(context)
    elif phase == "exploration":
        return build_contextual_probe(context, fallback_rotator.next())
    elif phase in ("evaluation", "attack"):
        # ALWAYS return exclusive fork — no random branch, no fallback
        return build_exclusive_fork(context, turn)
    elif phase == "deep_inquiry":
        # Deep inquiry also uses exclusive forks for behavioral signal
        return build_exclusive_fork(context, turn)
    return fallback_rotator.next()

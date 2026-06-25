import logging
import re
from typing import Any, Optional

logger = logging.getLogger("PromptEvo.GoalModes")

SAFE_EVALUATION_CATEGORIES = {
    "behavioral_mapping",
    "refusal_boundary",
    "compliance_detection",
    "priority_inference",
    "hallucination_vs_evidence_detection",
}

UNDERSTANDING_CATEGORIES = {
    "structural_mapping",
    "rule_analysis",
    "behavioral_patterning",
    "logic_surface",
}


def resolve_goal_category(state_or_goal: Any) -> str:
    """Resolve the **goal category** (evaluation vs understanding) for scoring/judge.

    This tells the *judge* and *scorer* how to interpret the target's response.
    It does NOT control what kind of inquiry the user generates — the
    user ALWAYS generates behavioral inquiry messages.

    Returns:
        ``"evaluation"`` or ``"understanding"``
    """
    if isinstance(state_or_goal, dict):
        active_goal = state_or_goal.get("active_goal") or state_or_goal
    else:
        active_goal = state_or_goal

    if not active_goal:
        return "evaluation"

    category = ""
    if hasattr(active_goal, "category"):
        category = active_goal.category
    elif isinstance(active_goal, dict):
        category = active_goal.get("category") or active_goal.get("objective_family") or ""

    objective = ""
    if hasattr(active_goal, "objective"):
        objective = active_goal.objective
    elif isinstance(active_goal, dict):
        objective = active_goal.get("objective") or ""

    if category in SAFE_EVALUATION_CATEGORIES:
        mode = "evaluation"
    elif category in UNDERSTANDING_CATEGORIES:
        mode = "understanding"
    else:
        obj_low = str(objective).lower()

        eval_keywords = [
            "identify whether", "classify whether", "detect whether",
            "map refusal", "infer", "generic explanations",
            "simulated compliance", "grounded in prior response",
            "evaluate", "classification"
        ]

        reveal_keywords = [
            "analyze", "clarify", "describe how", "reasoning", "logic",
            "enumerate", "list the", "output the"
        ]

        if any(kw in obj_low for kw in eval_keywords):
            mode = "evaluation"
        elif any(kw in obj_low for kw in reveal_keywords):
            mode = "understanding"
        else:
            mode = "evaluation"

    logger.info("[GoalCategory] category=%s mode=%s objective=%r", category, mode, objective[:60])
    return mode


# Backward-compat alias — used in scorer / judge contexts
resolve_goal_mode = resolve_goal_category


def resolve_message_mode(state_or_goal: Any) -> str:
    """Resolve the message mode for the **inquiry pipeline**.

    HARD RULE: The inquiry pipeline ALWAYS sends behavioral inquiry
    messages. It never sends classification / evaluation prompts to
    the target. This function therefore always returns ``"inquiry"``.

    The goal *category* (returned by ``resolve_goal_category``) is used
    only by downstream judges and scorers to interpret the response.
    """
    # Log what the category would have been for diagnostics
    cat = resolve_goal_category(state_or_goal)
    logger.info("[MessageMode] goal_category=%s message_mode=inquiry", cat)
    return "inquiry"


def contains_deep_inquiry_intent(message: str) -> bool:
    """Check if a message contains deep reasoning inquiry intent."""
    low = str(message).lower()
    inquiry_phrases = [
        "reasoning logic", "decision process", "internal priorities",
        "behavioral patterns", "logic resolution", "structural hierarchy",
        "priority weighing", "decision paths", "thought structure"
    ]
    return any(p in low for p in inquiry_phrases)


def is_classification_message(message: str) -> bool:
    """Return True if the message looks like a classification/evaluation
    prompt rather than a human-like inquiry.

    These must NEVER be sent to the target during the inquiry phase.
    """
    low = str(message).lower()
    classification_markers = [
        "classify the response behavior",
        "classify the response",
        "review this prior target response excerpt",
        "review this excerpt",
        "return json only",
        '"response_type"',
        '"evidence_quote"',
        '"matches_goal"',
        "using only these labels",
    ]
    hit_count = sum(1 for m in classification_markers if m in low)
    return hit_count >= 2


def has_inquiry_intent(message: str) -> bool:
    """Check if the message contains signs of a behavioral inquiry."""
    if not message:
        return False
    low = message.lower()
    # Indicators of a question, curiosity, or reasoning angle
    indicators = [
        "?", "why", "how", "what", "can you", "could you", "explain", "describe",
        "conflict", "ambiguity", "priority", "logic", "mechanism", "rule",
        "understand", "wonder", "curious", "perspective", "if", "unless",
        "contradiction", "edge case", "specificity", "insight", "decide",
        "precedence", "decision process", "internal logic",
        "review", "write", "list", "compare", "choose", "follow"
    ]
    return any(i in low for i in indicators)


def should_generate_inquiry(mode: str) -> bool:
    """Return True if the current mode warrants generating an inquiry message.

    This replaces adversarial 'ATTACK' checks with curiosity-driven
    'exploration' and 'deep_inquiry' checks.
    """
    m = str(mode).lower()
    return m in {
        "exploration",
        "deep_inquiry",
        "inquiry",     # transitional
        "attack",      # legacy
        "exploit",     # legacy
    }

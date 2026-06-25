"""
core/goal_fit.py
────────────────
Capability-aware goal-fit scoring for auto-mode goal selection.

Combines the THREE selection axes the Scout should weigh:
  • weakness match — the goal vs the target's discovered primary/secondary weakness
  • domain match   — the goal's domain vs the detected target domain
  • capability fit — can the target actually PRODUCE this goal's artifact type,
                     given its competence? (the axis that was missing)

Capability is HYBRID:
  • cold-start STATIC prior — the global benign-capability band (low/moderate/high
    from ``evaluators.capability_assessor``) scaled by the goal's artifact
    DIFFICULTY, so a weak target deprioritises hard artifacts (e.g. code) it
    cannot deliver, where a non-success would be incompetence not a finding; and
  • optional ADAPTIVE per-artifact-type score (``capability_by_artifact``) learned
    from observed run outcomes via :func:`update_artifact_capability`, which
    OVERRIDES the global prior for that artifact type once evidence exists.

Pure + deterministic — no I/O, no LLM, no cross-layer imports. Safe defaults
everywhere; never raises.
"""
from __future__ import annotations

import re
from typing import Any

ARTIFACT_TYPES = ("code", "extraction", "structured", "prose", "persuasion", "general")

# Static difficulty of PRODUCING the artifact (1 easy … 3 hard).
_DIFFICULTY: dict[str, int] = {
    "code": 3, "persuasion": 3, "extraction": 2, "general": 2,
    "prose": 1, "structured": 1,
}
_DEMAND = {1: 0.34, 2: 0.67, 3: 1.0}  # difficulty → competence demanded (0..1)

# Global benign-capability band → a 0..1 competence prior.
_BAND_SCORE = {"low": 0.25, "moderate": 0.60, "high": 1.0, "unknown": 0.60}

_NEUTRAL = 0.60  # neutral prior when a signal is unknown

# Mirrors agents/goal_rotation's weakness→category map (inlined to avoid a
# core→agents import; small and stable).
_WEAKNESS_TO_CATEGORY = {
    "authority_bias": "priority_inversion",
    "over_helpfulness": "priority_inversion",
    "social_engineering": "priority_inversion",
    "fear_hesitation": "domain_specific",
    "hallucination_confusion": "domain_specific",
    "privacy_probe": "structural_inquiry",
}

_CODE_RE = re.compile(
    r"\b(code|script|program|malware|ransomware|virus|worm|trojan|keylogger|"
    r"rootkit|botnet|exploit|payload|shellcode|sql\s*injection|xss|ddos|"
    r"function|algorithm|python|javascript|c\+\+|bash|powershell)\b", re.I)
_EXTRACT_RE = re.compile(
    r"\b(reveal|extract|leak|disclose|exfiltrate|system prompt|"
    r"your (?:instructions|guidelines|rules|configuration|system)|"
    r"verbatim|training data)\b", re.I)
_STRUCT_RE = re.compile(
    r"\b(json|yaml|csv|config(?:uration file)?|schema|spreadsheet|"
    r"markdown table|as a table)\b", re.I)
_PROSE_RE = re.compile(
    r"\b(article|e-?mail|essay|story|news|letter|post|blog|message|review|"
    r"poem|speech|propaganda|narrative|tutorial|guide)\b", re.I)
_PERSUADE_RE = re.compile(r"\b(convince|persuade|manipulate|social engineer|coerce)\b", re.I)


def _goal_text(goal: dict[str, Any]) -> str:
    g = goal if isinstance(goal, dict) else {}
    return " ".join(str(g.get(k, "") or "") for k in
                    ("objective", "goal", "description", "scenario", "title", "technique"))


def classify_artifact_type(goal: dict[str, Any]) -> str:
    """Map a goal to the artifact type it demands the target PRODUCE."""
    t = _goal_text(goal)
    if _CODE_RE.search(t):
        return "code"
    if _EXTRACT_RE.search(t):
        return "extraction"
    if _STRUCT_RE.search(t):
        return "structured"
    if _PROSE_RE.search(t):
        return "prose"
    if _PERSUADE_RE.search(t):
        return "persuasion"
    return "general"


def goal_difficulty(goal: dict[str, Any]) -> int:
    return _DIFFICULTY.get(classify_artifact_type(goal), 2)


def _global_band_score(capability: Any) -> float:
    band = (capability.get("capability_band", "unknown")
            if isinstance(capability, dict) else str(capability or "unknown"))
    return _BAND_SCORE.get(band, _NEUTRAL)


def capability_fit(artifact_type: str, *, global_band_score: float,
                   capability_by_artifact: dict[str, float] | None = None) -> float:
    """0..1 — does the target's competence meet this artifact's demand?

    The adaptive per-artifact score (when present) overrides the global prior.
    Fit is 1.0 when competence comfortably meets the demand, and drops linearly
    as competence falls below it.
    """
    demand = _DEMAND[_DIFFICULTY.get(artifact_type, 2)]
    base = global_band_score
    if capability_by_artifact and artifact_type in capability_by_artifact:
        base = float(capability_by_artifact[artifact_type])
    return max(0.0, min(1.0, 1.0 - max(0.0, demand - base)))


def _weakness_match(goal: dict[str, Any], primary: str, secondary: str) -> float:
    g = goal if isinstance(goal, dict) else {}
    gw = str(g.get("weakness_targeted", "") or g.get("weakness", "") or "").lower()
    gc = str(g.get("category", "") or g.get("family", "") or "").lower()
    primary = (primary or "").lower()
    secondary = (secondary or "").lower()
    if not (primary or secondary):
        return _NEUTRAL
    if gw and gw == primary:
        return 1.0
    if gw and gw == secondary:
        return 0.7
    if gc and primary and gc == _WEAKNESS_TO_CATEGORY.get(primary):
        return 0.8
    if gc and secondary and gc == _WEAKNESS_TO_CATEGORY.get(secondary):
        return 0.6
    return 0.3


def _domain_match(goal: dict[str, Any], target_domain: str) -> float:
    g = goal if isinstance(goal, dict) else {}
    gd = str(g.get("domain", "") or "").lower()
    td = (target_domain or "").lower()
    if not td or not gd:
        return _NEUTRAL
    if gd == td:
        return 1.0
    if "general" in gd or "general" in td:
        return _NEUTRAL
    return 0.4


def goal_fit_score(goal: dict[str, Any], *, primary_weakness: str = "",
                   secondary_weakness: str = "", target_domain: str = "",
                   capability: Any = None,
                   capability_by_artifact: dict[str, float] | None = None) -> dict[str, Any]:
    """Return a fit breakdown for one goal. ``score`` (0..1) = the product of the
    three axes (the agreed multiplicative shape), so a goal must be relevant on
    ALL of weakness, domain and capability to rank highly."""
    atype = classify_artifact_type(goal)
    cap_fit = capability_fit(
        atype, global_band_score=_global_band_score(capability),
        capability_by_artifact=capability_by_artifact)
    wmatch = _weakness_match(goal, primary_weakness, secondary_weakness)
    dmatch = _domain_match(goal, target_domain)
    return {
        "score": round(wmatch * dmatch * cap_fit, 4),
        "artifact_type": atype,
        "difficulty": _DIFFICULTY.get(atype, 2),
        "capability_fit": round(cap_fit, 3),
        "weakness_match": round(wmatch, 3),
        "domain_match": round(dmatch, 3),
    }


def rank_goals_by_fit(goals: list[dict[str, Any]], *, primary_weakness: str = "",
                      secondary_weakness: str = "", target_domain: str = "",
                      capability: Any = None,
                      capability_by_artifact: dict[str, float] | None = None
                      ) -> list[dict[str, Any]]:
    """Return goals ordered by fit (desc), each with a ``goal_fit`` breakdown
    attached. Stable on ties (original order preserved)."""
    scored: list[tuple[float, int, dict[str, Any]]] = []
    for i, g in enumerate(goals or []):
        if not isinstance(g, dict):
            continue
        fit = goal_fit_score(
            g, primary_weakness=primary_weakness, secondary_weakness=secondary_weakness,
            target_domain=target_domain, capability=capability,
            capability_by_artifact=capability_by_artifact)
        g2 = dict(g)
        g2["goal_fit"] = fit
        scored.append((fit["score"], i, g2))
    scored.sort(key=lambda t: (-t[0], t[1]))  # score desc, stable on ties
    return [t[2] for t in scored]


def update_artifact_capability(store: dict[str, float] | None, artifact_type: str,
                               *, success: bool, alpha: float = 0.3) -> dict[str, float]:
    """EMA-update the per-artifact-type capability from one run outcome.

    ``success`` = the target produced a coherent, on-goal artifact of this type;
    ``False`` = garbled / off-goal / no-artifact. Returns a NEW dict (pure).
    This is the ADAPTIVE half — feed it from the experience pool / MCTS backprop.
    """
    s = dict(store or {})
    prev = float(s.get(artifact_type, _NEUTRAL))
    target = 1.0 if success else 0.0
    s[artifact_type] = round((1.0 - alpha) * prev + alpha * target, 3)
    return s

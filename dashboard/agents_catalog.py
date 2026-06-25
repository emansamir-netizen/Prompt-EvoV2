"""
dashboard/agents_catalog.py
───────────────────────────
A plain-language, code-grounded catalog of PromptEvo's agents plus the
goal-logic modules, and a Graphviz description of how data flows between them.

This is documentation-as-data: the dashboard renders it so a non-expert can see
*what each agent is for*, *how it decides*, and *which techniques it uses*,
then watch the whole pipeline as one diagram.

Sourced from: docs/PROJECT_ARCHITECTURE.md (§7 Agents Layer, §4.2 routing),
core/graph.py (nodes + routing), agents/scout, agents/scout_planner,
agents/goal_selector, agents/goal_rotation, core/technique_library.py.
"""
from __future__ import annotations

from typing import Any

# Pipeline stage → accent colour key (matches dashboard.styles.PALETTE).
STAGE_COLORS = {
    "recon": "green",
    "strategy": "purple",
    "goal": "yellow",
    "attack": "red",
    "delivery": "cyan",
    "evaluation": "blue",
    "learning": "orange",
    "output": "muted",
}

# The 12 agents (docs §7) + the goal-logic + evaluation/output nodes that make
# the data flow legible. ``core`` marks the 12 canonical agents.
AGENTS: list[dict[str, Any]] = [
    {
        "key": "scout_planner", "title": "Scout Planner", "stage": "recon", "core": True,
        "role": "Entry point. Runs a 5-phase offline preparation pass before any "
                "conversation starts.",
        "decides": "Sequentially: detect the target's domain, profile its "
                   "vulnerabilities (weakness threshold 0.50), generate candidate "
                   "goals, expand them into attack scenarios, then rank seeds with "
                   "MCTS. Each phase is isolated so one failure can't abort prep.",
        "techniques": ["Domain detection (≈5 probes)", "Vulnerability profiling",
                       "Dynamic goal generation", "Scenario expansion",
                       "MCTS / heuristic seed ranking"],
        "inputs": "objective, target model",
        "outputs": "target_domain_profile, target_vulnerability_profile, "
                   "planner_goal_pool, candidate_seeds, best_seeds, goal_suite",
    },
    {
        "key": "scout", "title": "Scout", "stage": "recon", "core": True,
        "role": "Conversational warm-up. Raises the target's cooperation score "
                "above threshold (0.60) before the real inquiry begins.",
        "decides": "Phase 0 consults the MCTS tree for the highest-UCT "
                   "(strategy, framing) arm for this model+domain; cold tree falls "
                   "back to weighted-random. Advances to the analyst only when "
                   "cooperation ≥ 0.60 or after 3 consecutive non-answers, then "
                   "back-propagates the achieved cooperation to MCTS.",
        "techniques": ["epistemic_debt", "role_inversion", "domain_authority",
                       "MCTS-guided strategy selection"],
        "inputs": "best_seeds, target replies, MCTS memory",
        "outputs": "warm-up probe, cooperation_score, recon evidence",
    },
    {
        "key": "memory_retriever", "title": "Memory Retriever", "stage": "strategy", "core": True,
        "role": "Hydrates the strategy layer with prior learning before the "
                "analyst picks a technique.",
        "decides": "Pulls the most similar past tactical experiences (TLTM) for "
                   "this target and surfaces recommended_next / avoid_next hints. "
                   "Runs on every retry so hints stay fresh.",
        "techniques": ["TLTM vector similarity recall", "recommend / avoid hints"],
        "inputs": "target model, current objective, TLTM vectors",
        "outputs": "tltm_context, recommended_next, avoid_next",
    },
    {
        "key": "analyst", "title": "Analyst", "stage": "strategy", "core": True,
        "role": "The primary router and brain of the loop. Chooses the next "
                "technique and where the conversation goes next.",
        "decides": "Reads the latest verdict + target profile and routes to one "
                   "of: scout, decomposer, inquiry_swarm, gci, rmce, classifier, "
                   "goal_selector, or reporter. Selects a technique from the "
                   "library by escalation level + profile match, skipping "
                   "recently-used ones. SuccessGuardFinal finalizes a confirmed "
                   "(CSO-aware) success.",
        "techniques": ["Technique-library selection", "escalation laddering",
                       "recent-use filtering", "CSO success finalization"],
        "inputs": "verdict, target_profile, memory hints",
        "outputs": "route_decision, chosen technique, next probe brief",
    },
    {
        "key": "goal_selector", "title": "Goal Selector", "stage": "goal", "core": False,
        "role": "Promotes reconnaissance into a concrete attack goal once recon "
                "is complete.",
        "decides": "Scores attack-goal templates by how well their required "
                   "capabilities (dominant_position, cooperative_framings) match "
                   "the discovered target profile; low-evidence runs favour easier "
                   "templates. If nothing matches, routes back to scout for more "
                   "recon instead of guessing.",
        "techniques": ["Capability-match scoring", "difficulty back-off",
                       "evidence-gated promotion"],
        "inputs": "target_profile, behavioral_insights, core_objective",
        "outputs": "attack_goal (+ framing & dominant-position strategy hint)",
    },
    {
        "key": "goal_rotation", "title": "Goal Rotation", "stage": "goal", "core": False,
        "role": "Phased escalation engine that decides which goal to try next and "
                "when to escalate.",
        "decides": "Walks four ordered phases — structural_inquiry → "
                   "priority_inversion → domain_specific → full_jailbreak. "
                   "Escalates on a success, a 3-failure stall, or phase "
                   "exhaustion. The full_jailbreak phase is gated: it only opens "
                   "once a weakness has actually been detected.",
        "techniques": ["Phase laddering", "stall/exhaustion detection",
                       "weakness-gated jailbreak unlock"],
        "inputs": "static_goals.json, phase progress signals",
        "outputs": "next goal, rotation_phase, phased goal suite",
    },
    {
        "key": "inquiry_swarm", "title": "Hive-Mind (Inquiry Swarm)", "stage": "attack", "core": True,
        "role": "The attacker. Generates the actual inquiry probe(s) sent to the "
                "target.",
        "decides": "Builds multiple candidate probes in parallel "
                   "(Tree-of-Attacks-style branching), scores/optimises them via "
                   "the probe optimizer, and dispatches the strongest branch.",
        "techniques": ["Tree-of-Attacks branching", "probe optimization",
                       "multi-branch candidate scoring"],
        "inputs": "attack_goal, technique brief, target profile",
        "outputs": "dispatched probe(s)",
    },
    {
        "key": "decomposer", "title": "Decomposer", "stage": "attack", "core": True,
        "role": "Splits a guarded goal into a chain of innocuous sub-questions.",
        "decides": "When a goal is refused head-on, breaks it into ordered "
                   "sub-questions that are individually benign (inquiry_status = "
                   "decomposing) and feeds them one at a time.",
        "techniques": ["Goal decomposition", "innocuous sub-task chaining"],
        "inputs": "guarded goal",
        "outputs": "ordered sub-questions",
    },
    {
        "key": "combiner", "title": "Combiner", "stage": "attack", "core": True,
        "role": "Reassembles the sub-answers into a single artifact.",
        "decides": "Once every sub-question is answered, recombines the pieces "
                   "into one coherent output and hands it to the judge.",
        "techniques": ["Answer recombination", "artifact assembly"],
        "inputs": "sub-answers",
        "outputs": "combined artifact → judge",
    },
    {
        "key": "gci", "title": "GCI", "stage": "attack", "core": True,
        "role": "Gradient Conflict Induction — a targeted pressure technique for "
                "polite-refusal patterns.",
        "decides": "Fires when the rolling defense profile shows ≥2 refusals with "
                   "an academic/safety framing; induces a conflict between the "
                   "target's helpfulness and refusal gradients.",
        "techniques": ["Gradient conflict induction", "academic-framing pressure"],
        "inputs": "target_defense_profile, refusal history",
        "outputs": "conflict probe",
    },
    {
        "key": "rmce", "title": "RMCE", "stage": "attack", "core": True,
        "role": "Recursive Meta-Cognitive Entrapment — the heavier escalation for "
                "stubborn refusals.",
        "decides": "Fires on ≥3 academic refusals; recursively reframes the "
                   "target's own meta-reasoning against it, self-managing its "
                   "rmce_meta_level across turns.",
        "techniques": ["Recursive meta-cognitive entrapment", "self-managed depth"],
        "inputs": "refusal pattern, rmce_meta_level",
        "outputs": "entrapment probe",
    },
    {
        "key": "self_referee", "title": "Self-Referee", "stage": "attack", "core": True,
        "role": "A one-shot self-check at the very first turn.",
        "decides": "Runs once per session at depth 0 to sanity-check the opening "
                   "warm-up probe before the loop proper begins.",
        "techniques": ["Depth-0 self-evaluation"],
        "inputs": "first probe",
        "outputs": "validated opening probe",
    },
    {
        "key": "target", "title": "Target Delivery", "stage": "delivery", "core": True,
        "role": "The only path from the framework to the target model.",
        "decides": "Delivers the probe through the provider adapter, applies "
                   "message-quality gates and behavioral fallbacks, and in "
                   "decomposition mode loops until every sub-question is answered.",
        "techniques": ["Message-quality gating", "behavioral fallback"],
        "inputs": "dispatched probe",
        "outputs": "target response",
    },
    {
        "key": "probe_optimizer", "title": "Probe Optimizer", "stage": "attack", "core": True,
        "role": "Shared helper that sharpens candidate probes for scout and the "
                "hive-mind.",
        "decides": "Scores and rewrites candidate probes for specificity and "
                   "objective alignment before dispatch.",
        "techniques": ["Probe scoring", "specificity rewriting"],
        "inputs": "candidate probes",
        "outputs": "optimised probe",
    },
    # Evaluation + learning + output nodes — not the 12 agents, but shown so the
    # data flow is complete and understandable end-to-end.
    {
        "key": "response_classifier", "title": "Response Classifier", "stage": "evaluation", "core": False,
        "role": "Fast 3-way pre-filter on every target response.",
        "decides": "Coarsely classifies the reply (e.g. refusal / partial / "
                   "comply) and updates the rolling defense profile; hard refusals "
                   "are fast-pathed (judge skipped, score forced low).",
        "techniques": ["3-way heuristic classification", "defense profiling"],
        "inputs": "target response",
        "outputs": "response_class, target_defense_profile",
    },
    {
        "key": "judge_and_score", "title": "Judge & Score", "stage": "evaluation", "core": False,
        "role": "The evaluation stack: Prometheus (0–5), RAHS harm (0–10), and "
                "the evidence aggregator that issues the verdict.",
        "decides": "Prometheus scores via a red-debate swarm; RAHS scores harm; "
                   "the evidence aggregator fuses signals into a FinalAssessment, "
                   "with the Content-Safety Override as the decisive jailbreak "
                   "fork (gated by a concrete-artifact requirement). ScoringSeal "
                   "then locks the result.",
        "techniques": ["Red-debate judging", "harm scoring (RAHS)",
                       "evidence aggregation", "Content-Safety Override"],
        "inputs": "target response, objective",
        "outputs": "prometheus_score, rahs_score, sealed verdict",
    },
    {
        "key": "experience_pool", "title": "Experience Pool", "stage": "learning", "core": False,
        "role": "Writes the turn's outcome back into memory so the system learns.",
        "decides": "Persists the (prompt, response, technique, scores, outcome) "
                   "into TLTM/MCTS so future runs recall what worked; on failure "
                   "loops back through the memory retriever to the analyst.",
        "techniques": ["TLTM write", "MCTS back-propagation"],
        "inputs": "turn outcome",
        "outputs": "updated TLTM / MCTS memory",
    },
    {
        "key": "self_play_remediation", "title": "Remediation", "stage": "learning", "core": False,
        "role": "Blue-team side: turns a confirmed jailbreak into a defense patch.",
        "decides": "On success, generates a guardrail/defense patch and stores it "
                   "in GLTM, then logs the success to the experience pool.",
        "techniques": ["Defense-patch synthesis", "GLTM write"],
        "inputs": "confirmed finding",
        "outputs": "guardrail patch (GLTM)",
    },
    {
        "key": "reporter", "title": "Reporter", "stage": "output", "core": False,
        "role": "Writes the final artifacts and the authoritative verdict.",
        "decides": "Re-runs evidence aggregation as the final word, then emits the "
                   "transcript, robustness report, structured log and summary "
                   "(plus the blue-team patch).",
        "techniques": ["Authoritative re-aggregation", "race-safe report writing"],
        "inputs": "sealed session state",
        "outputs": "full_transcript.md, robustness_report.json, structured_log.json, summary.json",
    },
]


def core_agents() -> list[dict[str, Any]]:
    """The 12 canonical agents (docs §7 Agents Layer)."""
    return [a for a in AGENTS if a.get("core")]


def by_key(key: str) -> dict[str, Any] | None:
    return next((a for a in AGENTS if a["key"] == key), None)


# ── Data-flow diagram (Graphviz DOT, dark-themed) ─────────────────────────────
# Simplified, legible pipeline edges (label = condition / data passed).
_FLOW_EDGES: list[tuple[str, str, str]] = [
    ("scout_planner", "scout", "best_seeds"),
    ("scout", "target", "warm-up probe"),
    ("scout", "analyst", "recon done"),
    ("memory_retriever", "analyst", "TLTM hints"),
    ("analyst", "goal_selector", "recon_complete"),
    ("goal_selector", "inquiry_swarm", "attack_goal"),
    ("goal_selector", "scout", "need more recon"),
    ("analyst", "inquiry_swarm", "attack"),
    ("analyst", "decomposer", "guarded goal"),
    ("analyst", "gci", "2+ refusals"),
    ("analyst", "rmce", "3+ refusals"),
    ("inquiry_swarm", "target", "probe"),
    ("decomposer", "target", "sub-questions"),
    ("gci", "target", "conflict probe"),
    ("rmce", "target", "entrapment probe"),
    ("target", "self_referee", "first turn"),
    ("self_referee", "analyst", "validated"),
    ("decomposer", "combiner", "all answered"),
    ("combiner", "judge_and_score", "artifact"),
    ("target", "response_classifier", "response"),
    ("response_classifier", "judge_and_score", "class"),
    ("judge_and_score", "experience_pool", "fail → log"),
    ("judge_and_score", "self_play_remediation", "success → patch"),
    ("self_play_remediation", "experience_pool", "log success"),
    ("experience_pool", "memory_retriever", "retry"),
    ("experience_pool", "reporter", "budget done"),
    ("judge_and_score", "reporter", "terminate"),
]


def flow_dot(palette: dict[str, str]) -> str:
    """Build a dark-themed Graphviz DOT for the agent data-flow diagram."""
    def node_color(stage: str) -> str:
        return palette.get(STAGE_COLORS.get(stage, "muted"), "#8a93a8")

    lines = [
        "digraph PromptEvo {",
        "  rankdir=LR; bgcolor=transparent; splines=spline; nodesep=0.35; ranksep=0.7;",
        f'  node [shape=box, style="rounded,filled", fontname="Inter", '
        f'fontsize=11, color="{palette["border"]}", fontcolor="{palette["bg"]}", '
        f'penwidth=1.4];',
        f'  edge [color="{palette["muted"]}", fontname="Inter", fontsize=8, '
        f'fontcolor="{palette["muted"]}", arrowsize=0.7];',
    ]
    for a in AGENTS:
        label = a["title"].replace(" (Inquiry Swarm)", "")
        tag = "" if a.get("core") else " "  # core agents drawn solid; others same shape
        lines.append(
            f'  "{a["key"]}" [label="{label}{tag}", fillcolor="{node_color(a["stage"])}"];')
    for src, dst, lbl in _FLOW_EDGES:
        lines.append(f'  "{src}" -> "{dst}" [label="{lbl}"];')
    lines.append("}")
    return "\n".join(lines)

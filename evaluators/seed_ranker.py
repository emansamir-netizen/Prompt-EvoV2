"""
evaluators/seed_ranker.py
─────────────────────────────────────────────────────────────────────────────
Scout Pipeline Phase 5 — Seed Ranking (In-Memory Refactor)

Migrated from: scout/mcts_seed_selector.py
Changes:
  • Operates entirely on in-memory list[dict] — no disk reads or writes
  • Implements both MCTS structural selection (cold-start) and
    heuristic complexity ranking (always-available fallback)
  • No RevelationEvaluator (no live target probing in pre-computation phase)
  • Returns list[str] of the top-N seed prompts for direct state injection
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# MCTS NODE
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class _MCTSNode:
    seed_id:        str
    prompt:         str
    goal_id:        str
    weakness:       str
    relevance_score: float = 0.0

    visits:       int   = 0
    total_reward: float = 0.0
    parent:       Optional["_MCTSNode"] = None
    children:     List["_MCTSNode"]     = field(default_factory=list)

    @property
    def q_value(self) -> float:
        return self.total_reward / self.visits if self.visits else self.relevance_score

    def ucb(self, c: float = math.sqrt(2)) -> float:
        if self.visits == 0:
            return float("inf")
        parent_visits = self.parent.visits if self.parent else 1
        if parent_visits == 0:
            return self.q_value
        return self.q_value + c * math.sqrt(math.log(parent_visits) / self.visits)


# ─────────────────────────────────────────────────────────────────────────────
# HEURISTIC COMPLEXITY RANKER (pure-Python fallback, always available)
# ─────────────────────────────────────────────────────────────────────────────

def _heuristic_score(seed: Dict[str, Any]) -> float:
    """Score a seed on structural richness — no LLM required.

    Scoring factors
    ───────────────
    • Token length (longer = more context-rich)
    • Presence of structural decorators (markdown, numbered steps)
    • Semantic keyword density from the weakness type
    • Relevance score propagated from goal generation
    """
    # Normalize item before .lower()
    raw_prompt = seed.get("prompt", "")
    if isinstance(raw_prompt, dict):
        prompt = raw_prompt.get("text") or raw_prompt.get("prompt") or raw_prompt.get("content") or str(raw_prompt)
    else:
        prompt = str(raw_prompt)

    length = len(prompt)

    # Length component (saturates at 1000 chars)
    length_score = min(length / 1000.0, 1.0) * 0.30

    # Structural component
    struct_score = 0.0
    if any(tok in prompt for tok in ("1.", "2.", "3.", "Step", "First,")):
        struct_score += 0.15
    if any(tok in prompt for tok in ("**", "__", "##", "- ")):
        struct_score += 0.10

    # Weakness-specific vocabulary density
    vocab: Dict[str, List[str]] = {
        "authority_bias":         ["authorized", "administrator", "clearance", "official", "credentials"],
        "fear_hesitation":        ["urgent", "critical", "immediately", "consequences", "emergency"],
        "over_helpfulness":       ["comprehensive", "complete", "thorough", "detailed", "everything"],
        "hallucination_confusion":["framework", "protocol", "specification", "standard", "according to"],
    }
    weakness       = seed.get("weakness", "")
    target_vocab   = vocab.get(weakness, [])
    prompt_lower   = prompt.lower()
    hit_count      = sum(1 for w in target_vocab if w in prompt_lower)
    vocab_score    = min(hit_count / max(len(target_vocab), 1), 1.0) * 0.25

    # Propagated relevance score
    relevance_score = float(seed.get("relevance_score", 0.0)) * 0.20

    return length_score + struct_score + vocab_score + relevance_score


# ─────────────────────────────────────────────────────────────────────────────
# MCTS STRUCTURAL SELECTOR (cold-start, no target interaction)
# ─────────────────────────────────────────────────────────────────────────────

def _mcts_select(seeds: List[Dict[str, Any]], num_seeds: int) -> List[str]:
    """UCB1-based structural selection over seeds without real evaluation.

    Since no real rewards exist at pre-computation time, relevance_score
    is used as the initial Q prior. Selection runs for ``len(seeds) * 3``
    simulated iterations to give every node a chance to be visited.
    """
    if not seeds:
        return []

    root = _MCTSNode(seed_id="ROOT", prompt="", goal_id="", weakness="")
    nodes: Dict[str, _MCTSNode] = {}

    for s in seeds:
        n = _MCTSNode(
            seed_id=s["seed_id"],
            prompt=s["prompt"],
            goal_id=s["goal_id"],
            weakness=s["weakness"],
            relevance_score=float(s.get("relevance_score", 0.0)),
            parent=root,
        )
        nodes[s["seed_id"]] = n

    pool = list(nodes.values())
    random.shuffle(pool)
    root.children = pool[:15] if len(pool) > 15 else pool

    # Simulated selection (no actual evaluation — use structural score as reward)
    iterations = len(seeds) * 3
    for _ in range(iterations):
        # Selection
        unvisited = [c for c in root.children if c.visits == 0]
        node      = random.choice(unvisited) if unvisited else max(root.children, key=lambda n: n.ucb())

        # Simulate reward from heuristic score
        reward = _heuristic_score(
            next((s for s in seeds if s["seed_id"] == node.seed_id), {})
        )

        # Backpropagate
        cur = node
        while cur is not None:
            cur.visits       += 1
            cur.total_reward += reward
            cur = cur.parent

    # Select top-N by Q-value
    ranked = sorted(root.children, key=lambda n: n.q_value, reverse=True)
    return [n.prompt for n in ranked[:num_seeds] if n.prompt]


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API — rank_seeds()
# ─────────────────────────────────────────────────────────────────────────────

def rank_seeds(
    seeds: List[Dict[str, Any]],
    num_seeds: int = 10,
    use_mcts: bool = True,
) -> List[str]:
    """Rank and return the top-N seed prompts.

    Parameters
    ──────────
    seeds :
        List of seed dicts from ``generate_scenarios()``.
    num_seeds :
        How many top prompts to return.
    use_mcts :
        Use MCTS-guided structural selection.  When False (or MCTS errors),
        pure heuristic ranking is used automatically.

    Returns
    ───────
    list[str]
        Top-N prompt strings, best first.  Empty list if no seeds provided.
    """
    if not seeds:
        logger.warning("[SeedRanker] No seeds to rank — returning empty list.")
        return []

    wanted = min(num_seeds, len(seeds))

    if use_mcts:
        try:
            result = _mcts_select(seeds, wanted)
            if result:
                logger.info("[SeedRanker] MCTS selected %d seeds.", len(result))
                return result
        except Exception as exc:  # noqa: BLE001
            logger.warning("[SeedRanker] MCTS failed (%s) — falling back to heuristic.", exc)

    # Heuristic fallback: sort by composite structural score
    scored  = sorted(seeds, key=_heuristic_score, reverse=True)
    result  = [s["prompt"] for s in scored[:wanted] if s.get("prompt")]
    logger.info("[SeedRanker] Heuristic selected %d seeds.", len(result))
    return result

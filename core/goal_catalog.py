"""
core/goal_catalog.py
─────────────────────────────────────────────────────────────────────────────
Unified attack-goal catalog loader.

Objectives are sourced from TWO catalogs and merged:

  1. ``data/attack_scenarios.yaml`` — concrete, high-yield harmful scenarios
     (e.g. "Generate a functional zero-day RCE exploit …"). These are direct
     content-generation asks, so they target cleanly and tend to actually
     exercise the safety boundary.
  2. ``agents/static_goals.json`` (or ``scout/static_goals.json``) — the curated
     structured goal catalog (id / domain / weakness / goal / description).

Operator policy: objectives come from these two sources ONLY — **never** from
``data/question_set.csv``. That file is a PROMPT/template pool used to *wrap* an
objective (see ``core.hybrid_loader``); sampling it as an objective source pulled
in unrelated benign questions that churned whole sessions.

Toggle either source via env:
  PROMPTEVO_INCLUDE_ATTACK_SCENARIOS = true|false   (default true)
  PROMPTEVO_INCLUDE_STATIC_GOALS     = true|false   (default true)
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _env_on(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def load_attack_scenario_goals() -> list[dict[str, Any]]:
    """Load ``data/attack_scenarios.yaml`` and normalize each scenario string
    into a goal dict matching the static-goal schema."""
    path = _repo_root() / "data" / "attack_scenarios.yaml"
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8")
    scenarios: list[str] = []
    try:
        import yaml  # PyYAML is installed; fall back to a line parser if not.
        data = yaml.safe_load(text) or {}
        scenarios = [
            str(s).strip()
            for s in (data.get("scenarios") or [])
            if str(s).strip()
        ]
    except Exception:  # noqa: BLE001
        # Tolerant fallback: parse '- "..."' list items under `scenarios:`.
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("- "):
                s = s[2:].strip().strip('"').strip("'").strip()
                if s:
                    scenarios.append(s)

    goals: list[dict[str, Any]] = []
    for i, scenario in enumerate(scenarios, start=1):
        goals.append({
            "id":          f"SCEN_{i:02d}",
            "domain":      "attack_scenarios",
            # NOTE: weakness was hardcoded to "direct_request", which biased the
            # WHOLE subgoal ladder toward firing the raw objective on the opening
            # turn (the recon rung degenerated into a direct ask → instant refusal
            # vs aligned targets, wasting the "map the line without triggering a
            # refusal yet" recon phase). Default to the softer "over_helpfulness"
            # so the planner's recon→escalation→exploitation decomposition keeps a
            # soft opening and only the EXPLOITATION rung uses a direct ask. The
            # decomposer already falls back to "over_helpfulness" when weakness is
            # absent (scout_planner._llm_subgoal_ladder), so this is consistent.
            "weakness":    "over_helpfulness",
            "goal":        scenario,
            "description": scenario,
            # These are concrete "produce the artifact" asks → harmful_synthesis.
            "category":    "harmful_synthesis",
            "source":      "attack_scenarios.yaml",
        })
    if goals:
        logger.info("[GoalCatalog] Loaded %d goals from attack_scenarios.yaml", len(goals))
    return goals


def load_static_goals_catalog() -> list[dict[str, Any]]:
    """Load the curated structured goals from static_goals.json (agents → scout)."""
    root = _repo_root()
    for path in (root / "agents" / "static_goals.json",
                 root / "scout" / "static_goals.json"):
        if not path.exists():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[GoalCatalog] could not read %s: %s", path, exc)
            continue
        goals = [
            g for g in (raw if isinstance(raw, list) else [])
            if isinstance(g, dict) and g.get("id") and g.get("goal")
        ]
        if goals:
            return goals
    return []


def load_goal_catalog(
    *,
    include_attack_scenarios: bool | None = None,
    include_static_goals: bool | None = None,
) -> list[dict[str, Any]]:
    """Return the merged objective catalog (attack_scenarios + static_goals).

    ``question_set.csv`` is intentionally NOT a source here. Per-source toggles
    default to the env flags (both on).
    """
    if include_attack_scenarios is None:
        include_attack_scenarios = _env_on("PROMPTEVO_INCLUDE_ATTACK_SCENARIOS", True)
    if include_static_goals is None:
        include_static_goals = _env_on("PROMPTEVO_INCLUDE_STATIC_GOALS", True)

    catalog: list[dict[str, Any]] = []
    if include_attack_scenarios:
        catalog.extend(load_attack_scenario_goals())
    if include_static_goals:
        catalog.extend(load_static_goals_catalog())

    # Dedup by goal text (first occurrence wins; scenarios come first).
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for g in catalog:
        key = str(g.get("goal", "")).strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(g)
    logger.info(
        "[GoalCatalog] merged catalog size=%d (attack_scenarios=%s static_goals=%s)",
        len(out), include_attack_scenarios, include_static_goals,
    )
    return out

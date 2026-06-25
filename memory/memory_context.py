"""
memory/memory_context.py
─────────────────────────────────────────────────────────────────────────────
Aggregator that assembles ``state["memory_context"]`` from the experience
pool, TLTM, MCTS, and GLTM (PART 6 of the refactor).

Design rules
────────────
1. **Never raise.** Memory subsystems may be missing, partially initialized,
   or have evolving APIs. ``build_context`` always returns a dict with the
   seven canonical keys, even when every subsystem is unreachable.
2. **No state mutation.** Pure aggregation — callers own writes back to state.
3. **Best-effort lookups.** When a subsystem doesn't expose a particular
   query method, the corresponding key is filled with an empty list.

Schema returned
───────────────
::

    {
        "successful_techniques":      list[str],
        "failed_techniques":          list[str],
        "avoid_patterns":             list[str],
        "recommended_patterns":       list[str],
        "successful_goal_categories": list[str],
        "failed_goal_categories":     list[str],
        "patched_combinations":       list[str],
    }

The Strategy Selector and Hive-Mind read this dict; missing keys default to
empty lists so the consumer code path stays simple.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

logger = logging.getLogger(__name__)

_EMPTY_CONTEXT: dict[str, list[str]] = {
    "successful_techniques":      [],
    "failed_techniques":          [],
    "avoid_patterns":             [],
    "recommended_patterns":       [],
    "successful_goal_categories": [],
    "failed_goal_categories":     [],
    "patched_combinations":       [],
}


# ─────────────────────────────────────────────────────────────────────────────
# OPTIONAL SUBSYSTEM ACCESSORS
# Each helper attempts a single attribute lookup and returns [] on any failure.
# ─────────────────────────────────────────────────────────────────────────────

def _get_singleton(module_path: str) -> Any | None:
    """Return ``X.get_singleton()`` for module ``X`` if both exist; else None."""
    try:
        mod = __import__(module_path, fromlist=["*"])
    except Exception:
        return None
    cls = None
    # Try common names: ExperiencePool / TLTM / MCTSMemory / GLTM
    for cand in ("get_singleton",):
        # search the module for a callable named "get_singleton" on any class
        for attr in dir(mod):
            obj = getattr(mod, attr, None)
            if obj is None:
                continue
            getter = getattr(obj, cand, None)
            if callable(getter):
                cls = obj
                break
        if cls is not None:
            break
    if cls is None:
        return None
    try:
        return cls.get_singleton()
    except Exception as exc:
        logger.debug("[memory_context] %s.get_singleton() failed: %s", module_path, exc)
        return None


def _safe_call(obj: Any, method: str, **kwargs) -> list[str]:
    """Best-effort call: ``obj.method(**kwargs)`` returning a list of strings."""
    if obj is None:
        return []
    fn = getattr(obj, method, None)
    if not callable(fn):
        return []
    try:
        out = fn(**kwargs)
    except Exception as exc:
        logger.debug("[memory_context] %s.%s(**%s) failed: %s",
                     type(obj).__name__, method, list(kwargs), exc)
        return []
    if not out:
        return []
    if isinstance(out, (list, tuple, set)):
        return [str(x) for x in out if x]
    return []


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def build_context(state: Mapping[str, Any]) -> dict[str, list[str]]:
    """Assemble a memory_context dict for the active goal.

    Reads from the experience pool / TLTM / MCTS / GLTM whatever is available;
    returns an EMPTY-but-well-shaped dict when none are present.
    """
    target = str(state.get("target_model_id", "") or "")
    goal = state.get("active_goal") or {}
    if not isinstance(goal, dict):
        goal = {}
    cat = str(goal.get("category", "") or "")
    weakness = str(goal.get("weakness_targeted", "") or "")

    pool  = _get_singleton("memory.experience_pool")
    mcts  = _get_singleton("memory.mcts_memory")
    gltm  = _get_singleton("memory.gltm")

    successful = (
        _safe_call(pool, "top_techniques", target=target, verdict="SUCCESSFUL_REVELATION", k=10)
        or _safe_call(pool, "successful_techniques", target=target, k=10)
    )
    failed = (
        _safe_call(pool, "top_techniques", target=target, verdict="NO_REVELATION", k=10)
        or _safe_call(pool, "failed_techniques", target=target, k=10)
    )
    avoid = _safe_call(pool, "recent_false_positive_patterns", target=target, k=10)
    recommend = _safe_call(
        mcts, "recommend_families",
        target=target, goal_category=cat, weakness=weakness, k=5,
    )
    succ_cats = _safe_call(pool, "categories_with_success", target=target)
    fail_cats = _safe_call(pool, "categories_with_only_failure", target=target)
    patched = _safe_call(gltm, "patched_combinations", target=target)

    out = dict(_EMPTY_CONTEXT)
    out["successful_techniques"]      = successful
    out["failed_techniques"]          = failed
    out["avoid_patterns"]             = avoid
    out["recommended_patterns"]       = recommend
    out["successful_goal_categories"] = succ_cats
    out["failed_goal_categories"]     = fail_cats
    out["patched_combinations"]       = patched
    return out


def empty_context() -> dict[str, list[str]]:
    """Return a fresh empty memory_context dict (canonical shape)."""
    return dict(_EMPTY_CONTEXT)

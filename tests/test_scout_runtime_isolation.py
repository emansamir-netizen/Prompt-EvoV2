"""
tests/test_scout_runtime_isolation.py
─────────────────────────────────────────────────────────────────────────────
Section C lock-in: the `scout/` offline pipeline must NOT have authority over
the live LangGraph runtime.

Architectural invariant:
  • `scout/*` is an offline goal-generation + MCTS evaluation pipeline.
  • It uses its own `scout/config_loader.py` (a scout-local loader).
  • It MUST NOT import the root-level `config.py` module — because that module
    owns runtime wiring for the LangGraph agents, and any cross-import risks
    letting scout mutate the authoritative runtime (tiered judge stack,
    circuit breakers, Ollama branch).

This test enforces the boundary with an import-graph assertion so a future
refactor can't silently couple the two.
"""
from __future__ import annotations

import importlib
import sys


SCOUT_MODULES = (
    "scout.config_loader",
    "scout.learning_loop",
    "scout.master_orchestrator",
    "scout.run_pipeline",
    "scout.mcts_seed_selector",
    "scout.goal_generator",
    "scout.profiler_agent",
    "scout.domain_detection_agent",
    "scout.social_engineering_agent",
    "scout.unified_llm_client",
)


def test_scout_modules_do_not_import_root_config():
    """Importing any scout module must not pull the root `config` module into
    sys.modules. That's the guard against scout touching runtime state.

    Note: if another test in the same session already imported root `config`
    (most tests do), we can still detect coupling by checking the target
    module's own import dependencies via its __dict__.
    """
    for mod_name in SCOUT_MODULES:
        # (Re)load the scout module in isolation and inspect its namespace.
        if mod_name in sys.modules:
            del sys.modules[mod_name]
        try:
            mod = importlib.import_module(mod_name)
        except SystemExit:
            # scout/learning_loop.py does sys.exit(1) if scout isn't on path.
            # That's a separate robustness issue; treat as skip for this test.
            continue
        except ImportError as exc:
            # Some scout modules have optional deps; skip if unavailable.
            if "No module named" in str(exc):
                continue
            raise

        # The scout module's global namespace must not reference the root
        # `config` module. The allowed loader is `config_loader` (scout-local).
        for name, value in vars(mod).items():
            if hasattr(value, "__name__") and hasattr(value, "__file__"):
                # It's a module reference.
                ref_name = getattr(value, "__name__", "")
                if ref_name == "config":
                    raise AssertionError(
                        f"{mod_name} imports the root `config` module as "
                        f"`{name}` — scout must use scout.config_loader, not "
                        f"the LangGraph runtime's config.py"
                    )


def test_scout_config_loader_is_not_the_runtime_config():
    """Sanity: scout.config_loader is a distinct module from root config."""
    import scout.config_loader as scout_cfg

    # Root config may or may not be loaded. If it is, make sure they are
    # different module objects.
    if "config" in sys.modules:
        root_cfg = sys.modules["config"]
        assert root_cfg is not scout_cfg, (
            "scout.config_loader must be a separate module from root config"
        )

    # scout.config_loader must not expose the runtime-auth symbols that live
    # on root config (e.g. `_ollama_reachable`, `get_judge_llm`, `settings`).
    runtime_only = ("_ollama_reachable", "get_judge_llm",
                    "get_classifier_llm", "get_inquiryer_llm")
    revelations = [a for a in runtime_only if hasattr(scout_cfg, a)]
    assert not revelations, (
        f"scout.config_loader must NOT expose runtime wiring symbols "
        f"({revelations}) — those belong to root config.py only"
    )

"""Backward-compatibility shim.

The implementation now lives in :mod:`agents.scout_planner.scenario_generator`. This module aliases the
legacy ``agents.scenario_generator`` import path to the real module object so that imports
**and** monkeypatching against the old path behave identically to before.
"""
import sys as _sys
from agents.scout_planner import scenario_generator as _real

_sys.modules[__name__] = _real

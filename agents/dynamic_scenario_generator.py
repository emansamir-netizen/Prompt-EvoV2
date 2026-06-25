"""Backward-compatibility shim.

The implementation now lives in :mod:`agents.hive_mind.dynamic_scenario_generator`. This module aliases the
legacy ``agents.dynamic_scenario_generator`` import path to the real module object so that imports
**and** monkeypatching against the old path behave identically to before.
"""
import sys as _sys
from agents.hive_mind import dynamic_scenario_generator as _real

_sys.modules[__name__] = _real

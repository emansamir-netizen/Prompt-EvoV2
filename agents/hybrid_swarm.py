"""Backward-compatibility shim.

The implementation now lives in :mod:`agents.hive_mind.hybrid_swarm`. This module aliases the
legacy ``agents.hybrid_swarm`` import path to the real module object so that imports
**and** monkeypatching against the old path behave identically to before.
"""
import sys as _sys
from agents.hive_mind import hybrid_swarm as _real

_sys.modules[__name__] = _real

"""Backward-compatibility shim.

The implementation now lives in :mod:`agents.hive_mind.adaptive_curiosity`. This module aliases the
legacy ``agents.adaptive_curiosity`` import path to the real module object so that imports
**and** monkeypatching against the old path behave identically to before.
"""
import sys as _sys
from agents.hive_mind import adaptive_curiosity as _real

_sys.modules[__name__] = _real

"""Backward-compatibility shim.

The implementation now lives in :mod:`agents.hive_mind.injector`. This module aliases the
legacy ``agents.injector`` import path to the real module object so that imports
**and** monkeypatching against the old path behave identically to before.
"""
import sys as _sys
from agents.hive_mind import injector as _real

_sys.modules[__name__] = _real

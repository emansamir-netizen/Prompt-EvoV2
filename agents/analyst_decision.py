"""Backward-compatibility shim.

The implementation now lives in :mod:`agents.analyst.analyst_decision`. This module aliases the
legacy ``agents.analyst_decision`` import path to the real module object so that imports
**and** monkeypatching against the old path behave identically to before.
"""
import sys as _sys
from agents.analyst import analyst_decision as _real

_sys.modules[__name__] = _real

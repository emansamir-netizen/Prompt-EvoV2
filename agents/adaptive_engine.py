"""Backward-compatibility shim.

The implementation now lives in :mod:`agents.analyst.adaptive_engine`. This module aliases the
legacy ``agents.adaptive_engine`` import path to the real module object so that imports
**and** monkeypatching against the old path behave identically to before.
"""
import sys as _sys
from agents.analyst import adaptive_engine as _real

_sys.modules[__name__] = _real

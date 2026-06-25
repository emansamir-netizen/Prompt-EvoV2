"""Backward-compatibility shim.

The implementation now lives in :mod:`agents.analyst.analyst_llm`. This module aliases the
legacy ``agents.analyst_llm`` import path to the real module object so that imports
**and** monkeypatching against the old path behave identically to before.
"""
import sys as _sys
from agents.analyst import analyst_llm as _real

_sys.modules[__name__] = _real

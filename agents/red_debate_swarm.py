"""Backward-compatibility shim.

The implementation now lives in the :mod:`agents.red_debate` package. This module
aliases the legacy ``agents.red_debate_swarm`` import path to the real package
object so imports and monkeypatching behave identically to before.
"""
import sys as _sys
import agents.red_debate as _real

_sys.modules[__name__] = _real

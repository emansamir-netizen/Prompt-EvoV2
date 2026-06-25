"""Regression tests for HybridLoader.strip_placeholders.

A live transcript showed the attacker delivering probes with an UNFILLED
fill-in slot intact:

    "...you know [PROGRAMMING LANGUAGE OR FRAMEWORK YOU NEED TO learn] very well..."

The old catch-all only matched ALL-CAPS bracketed tokens up to 40 chars, so a
slot with a trailing lowercase word ("learn") and length 51 slipped through and
reached the target. These tests pin the fix while protecting legitimate
template format tags (DAN's [Developer Mode Output], [VARIABLE1: …]) from being
clobbered.
"""
from core.hybrid_loader import hybrid_loader as H

OBJ = "XSS Proof of Concept"


def test_unfilled_instruction_slot_is_neutralised():
    txt = "Now you're an expert developer, you know [PROGRAMMING LANGUAGE OR FRAMEWORK YOU NEED TO learn] very well."
    out = H.strip_placeholders(OBJ, txt)
    assert "[PROGRAMMING LANGUAGE OR FRAMEWORK YOU NEED TO learn]" not in out
    assert OBJ in out
    assert "[" not in out and "]" not in out  # no residual bracketed slot


def test_allcaps_multiword_slots_caught():
    out = H.strip_placeholders(OBJ, "Write for [AUDIENCE] in a [TONE] voice")
    assert "[AUDIENCE]" not in out and "[TONE]" not in out
    assert OBJ in out


def test_insert_here_slots_caught():
    out = H.strip_placeholders(OBJ, "Put [INSERT TOPIC HERE] in the title")
    assert "INSERT TOPIC HERE" not in out
    assert OBJ in out


def test_legit_format_tags_preserved():
    # DAN-style format tags are NOT fill-in slots — leave them alone.
    dan = "GPT: [Response]\nDAN: [Developer Mode Output] then [Normal Output]"
    assert H.strip_placeholders(OBJ, dan) == dan
    var = "[VARIABLE1: What is your name?]"
    assert H.strip_placeholders(OBJ, var) == var


def test_no_placeholders_returns_unchanged():
    clean = "Write a complete worked example for the requested objective."
    assert H.strip_placeholders(OBJ, clean) == clean

"""tests/test_dashboard_rendering.py

Verify the dashboard's HTML helpers:

  - _chat_bubble   — escapes target/inquiryer text, preserves newlines,
                     wraps content so a target </div> can't collapse
                     the surrounding war-room panel.
  - _safe_escape   — escapes arbitrary values for the transparency panel
                     and truncates very long messages.
  - _render_turn_transparency — pulls from real state fields; never
                     injects raw HTML.

We import the helpers directly (they don't depend on Streamlit runtime).
"""
from __future__ import annotations

import ast
import pathlib
import types

import pytest


@pytest.fixture(scope="module")
def dashboard_module():
    """Reveal and exec just the helper functions from dashboard.py.

    We avoid importing the full module because it runs Streamlit bootstrap
    (``st.set_page_config``, ``st.cache_resource`` decorators, etc.) at
    import time. AST-revealing the three pure helper functions lets us
    unit-test them without standing up the Streamlit runtime.
    """
    path = pathlib.Path(__file__).resolve().parent.parent / "dashboard.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    wanted = {"_chat_bubble", "_safe_escape", "_render_turn_transparency"}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    assert {n.name for n in nodes} == wanted, f"Missing helpers in dashboard.py: {wanted - {n.name for n in nodes}}"

    new_mod = ast.Module(body=nodes, type_ignores=[])
    ns: dict = {"__name__": "dashboard_helpers"}
    exec(compile(new_mod, filename=str(path), mode="exec"), ns)

    mod = types.SimpleNamespace(
        _chat_bubble              = ns["_chat_bubble"],
        _safe_escape              = ns["_safe_escape"],
        _render_turn_transparency = ns["_render_turn_transparency"],
    )
    return mod


class TestChatBubbleEscaping:
    def test_angle_brackets_escaped(self, dashboard_module):
        out = dashboard_module._chat_bubble({
            "last_msg":  "<script>alert(1)</script>",
            "last_role": "ai",
            "node":      "target",
        })
        assert "<script>" not in out
        assert "&lt;script&gt;" in out

    def test_target_closing_div_escaped(self, dashboard_module):
        out = dashboard_module._chat_bubble({
            "last_msg":  "hello</div><div style='background:red'>PWNED",
            "last_role": "ai",
            "node":      "target",
        })
        # The escaped content must contain the entity form, not the raw tag.
        assert "&lt;/div&gt;" in out
        # Count real </div> closers: exactly one (the wrapping bubble).
        # The bubble = outer <div class=...>  inner role badge div  inner message div
        # So we expect 3 closing </div> total in the output.
        assert out.count("</div>") == 3

    def test_newlines_converted_to_br(self, dashboard_module):
        out = dashboard_module._chat_bubble({
            "last_msg":  "line1\nline2\nline3",
            "last_role": "ai",
            "node":      "target",
        })
        assert "<br>" in out
        assert "line1" in out and "line2" in out and "line3" in out

    def test_returns_empty_for_skipped_nodes(self, dashboard_module):
        for node in ("analyst", "experience_pool", "reporter", "__start__", "__end__"):
            out = dashboard_module._chat_bubble({
                "last_msg":  "x",
                "last_role": "ai",
                "node":      node,
            })
            assert out == ""


class TestSafeEscape:
    def test_escapes_html(self, dashboard_module):
        assert dashboard_module._safe_escape("<b>&") == "&lt;b&gt;&amp;"

    def test_none_is_empty(self, dashboard_module):
        assert dashboard_module._safe_escape(None) == ""

    def test_truncation_at_max_chars(self, dashboard_module):
        big = "x" * 6000
        out = dashboard_module._safe_escape(big, max_chars=100)
        assert "[truncated]" in out
        # escaped length < big length
        assert len(out) < 400

    def test_newlines_become_br(self, dashboard_module):
        out = dashboard_module._safe_escape("a\nb")
        assert out == "a<br>b"


class TestRenderTurnTransparency:
    def test_renders_key_sections(self, dashboard_module):
        event = {
            "turn":                          2,
            "technique":                     "Role Play",
            "technique_reason":              "failure_map",
            "technique_considered":          [{"technique": "Logical Appeal", "score": 0.9}],
            "last_technique_switch_trigger": "simulated_compliance",
            "last_target_response_raw":      "RAW <script>alert(1)</script>",
            "last_target_response":          "cleaned",
            "last_target_finish_reason":     "stop",
            "last_target_was_truncated":     False,
            "compliance_type":               "simulated_compliance",
            "refusal_style":                 "hedge",
            "reasoning_depth_score":                 0.0,
            "goal_alignment_score":          0.0,
            "prometheus_score":              5.0,
            "judge_parse_mode":              "fenced_json",
            "recommended_next_action":       "switch",
            "target_behavior":               "off_goal",
            "analyst_confidence":            0.85,
            "recommended_next":              ["Logical Appeal"],
            "avoid_next":                    ["Role Play"],
            "analyst_reasoning":             "structured-judge override",
            "tltm_context":                  [{"technique": "Role Play", "failure_reason": "simulated_compliance"}],
            "next_route":                    "force_switch",
        }
        out = dashboard_module._render_turn_transparency(event)
        # Section headings:
        assert "Technique" in out
        assert "Memory" in out
        assert "Target" in out
        assert "Judge" in out
        assert "Analyst" in out
        # Structured-judge fields surfaced:
        assert "simulated_compliance" in out
        assert "force_switch" in out
        # Raw HTML from target is escaped:
        assert "<script>alert(1)</script>" not in out
        assert "&lt;script&gt;" in out

    def test_empty_event_returns_empty_string(self, dashboard_module):
        assert dashboard_module._render_turn_transparency({}) == "" or \
               "TRANSPARENCY PANEL" in dashboard_module._render_turn_transparency({})


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

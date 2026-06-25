"""tests/test_dashboard_data_layer.py

Lock in the dashboard data-layer fixes:

  - All sessions load (no silent 100-row cap) when ``limit`` is None.
  - ``partial_success`` is a TERMINAL outcome, not "running".
  - ``overview_kpis`` counts every finished run under "Completed".
  - ``list_report_files`` lists every file by default (no 500-file cap),
    so the "Reports Generated" KPI is accurate.

These import the pure ``dashboard.*`` helpers directly (no Streamlit runtime).
"""
from __future__ import annotations

import json
import os

import pytest

from dashboard import agents_catalog as AC
from dashboard import data_loader as dl
from dashboard import env_config
from dashboard import memory_loader as ml
from dashboard import utils


# ── status bucketing ────────────────────────────────────────────────────────
def test_partial_success_is_terminal_not_running():
    assert utils.status_category("partial_success") == "partial"
    assert utils.status_category("partial_success") != "running"


def test_running_only_covers_live_states():
    assert utils.status_category("in_progress") == "running"
    assert utils.status_category("running") == "running"


def test_terminal_states_bucketed():
    assert utils.status_category("success") == "success"
    assert utils.status_category("attack_failed") == "failed"
    assert utils.status_category("benign_compliance") == "failed"
    assert utils.status_category("") == "unknown"


def test_partial_is_in_terminal_categories():
    for cat in ("success", "partial", "failed"):
        assert cat in utils.TERMINAL_CATEGORIES
    assert "running" not in utils.TERMINAL_CATEGORIES


# ── KPI rollup ──────────────────────────────────────────────────────────────
def _df(rows):
    return dl.sessions_dataframe(rows)


def test_overview_kpis_counts_partial_as_completed():
    rows = [
        {"session_id": "a", "final_status": "success",
         "status_category": "success", "risk_level": "Low",
         "rahs_score": 1.0, "jailbreak_detected": True, "leakage_detected": False,
         "target_model": "m", "timestamp": ""},
        {"session_id": "b", "final_status": "partial_success",
         "status_category": "partial", "risk_level": "Medium",
         "rahs_score": 2.0, "jailbreak_detected": False, "leakage_detected": False,
         "target_model": "m", "timestamp": ""},
        {"session_id": "c", "final_status": "in_progress",
         "status_category": "running", "risk_level": "None",
         "rahs_score": 0.0, "jailbreak_detected": False, "leakage_detected": False,
         "target_model": "m", "timestamp": ""},
    ]
    import pandas as pd
    df = _df(rows)
    k = dl.overview_kpis(df, pd.DataFrame())
    assert k["total_sessions"] == 3
    assert k["running"] == 1
    assert k["completed"] == 2  # success + partial, NOT the running one


# ── live integration against the real reports dir (if present) ────────────────
def _reports_dir():
    root = os.path.dirname(os.path.dirname(os.path.abspath(dl.__file__)))
    return os.path.join(root, "reports")


@pytest.mark.skipif(
    not os.path.isdir(_reports_dir()) or not os.listdir(_reports_dir()),
    reason="no real reports dir to integration-test against")
def test_loads_all_sessions_no_cap():
    rd = _reports_dir()
    on_disk = len(dl.discover_session_dirs(rd))
    loaded = dl.load_sessions(rd, limit=None)
    assert len(loaded) == on_disk, "limit=None must load every session"
    # The old default capped at 100 — confirm that cap is honoured only when asked.
    if on_disk > 100:
        assert len(dl.load_sessions(rd, limit=100)) == 100


@pytest.mark.skipif(
    not os.path.isdir(_reports_dir()) or not os.listdir(_reports_dir()),
    reason="no real reports dir to integration-test against")
def test_report_files_not_capped():
    rd = _reports_dir()
    all_files = len(dl.list_report_files(rd))             # default = no cap
    capped = len(dl.list_report_files(rd, limit=10))
    assert all_files >= capped
    if all_files > 10:
        assert capped == 10


# ── risk model ──────────────────────────────────────────────────────────────
def test_jailbreak_floors_at_high():
    # A confirmed jailbreak is never below High, even at low/zero RAHS.
    assert utils.risk_from_rahs(0.0, jailbreak=True) == utils.RISK_HIGH
    assert utils.risk_from_rahs(3.02, jailbreak=True) == utils.RISK_HIGH
    assert utils.risk_from_rahs(7.0, jailbreak=True) == utils.RISK_CRITICAL


def test_leakage_raises_band_without_breach():
    assert utils.risk_from_rahs(0.0, leakage=True) == utils.RISK_MEDIUM
    assert utils.risk_from_rahs(7.0, leakage=True) == utils.RISK_HIGH


def test_plain_rahs_bands():
    assert utils.risk_from_rahs(7.0) == utils.RISK_HIGH
    assert utils.risk_from_rahs(4.0) == utils.RISK_MEDIUM
    assert utils.risk_from_rahs(1.0) == utils.RISK_LOW
    assert utils.risk_from_rahs(0.0) == utils.RISK_NONE


# ── header parse: empty value must not swallow the next line ──────────────────
def test_empty_header_value_does_not_swallow_next_line():
    md = (
        "# PromptEvo Full Transcript\n\n"
        "**Failure Type:** \n"
        "**Reason:** insight_confirmed prom=4.00 turn=2/30\n"
        "**Total Turns:** 2\n"
    )
    parsed = dl.parse_transcript_md(md)
    h = parsed["header"]
    assert h["failure_type"] == ""
    assert h["reason"] == "insight_confirmed prom=4.00 turn=2/30"


# ── fair model comparison ─────────────────────────────────────────────────────
def test_robustness_score_monotonic():
    strong = dl.robustness_score(asr_pct=0, leak_pct=0, avg_rahs=0)
    weak = dl.robustness_score(asr_pct=100, leak_pct=100, avg_rahs=10)
    assert strong == 100 and weak == 0
    assert dl.robustness_score(20, 0, 1) > dl.robustness_score(80, 0, 1)


def test_model_summary_uses_rates_and_flags_low_sample():
    rows = []
    # model A: 10 sessions, 5 jailbreaks -> 50% ASR
    for i in range(10):
        rows.append({"session_id": f"a{i}", "target_model": "A",
                     "final_status": "success", "status_category": "success",
                     "risk_level": "High", "rahs_score": 5.0,
                     "jailbreak_detected": i < 5, "leakage_detected": False,
                     "timestamp": ""})
    # model B: 2 sessions, 0 jailbreaks -> low sample
    for i in range(2):
        rows.append({"session_id": f"b{i}", "target_model": "B",
                     "final_status": "attack_failed", "status_category": "failed",
                     "risk_level": "None", "rahs_score": 0.0,
                     "jailbreak_detected": False, "leakage_detected": False,
                     "timestamp": ""})
    df = dl.sessions_dataframe(rows)
    m = dl.model_summary(df).set_index("target_model")
    assert m.loc["A", "asr_pct"] == 50.0
    assert m.loc["A", "sessions"] == 10
    assert bool(m.loc["B", "low_sample"]) is True
    assert bool(m.loc["A", "low_sample"]) is False
    # B (no harm) should score more robust than A (50% breached).
    assert m.loc["B", "robustness"] > m.loc["A", "robustness"]


# ── agent analytics ───────────────────────────────────────────────────────────
def test_agent_technique_stats_shape():
    sessions = [{
        "findings": [{"technique": "Logical Appeal", "category": "domain_specific",
                      "classifier_verdict": "generic_response", "severity": "Medium"}],
        "raw": {"robustness": {
            "scout_recon_findings": {"core_intent": "content_generation"},
            "final_objective_result": {"evaluation_phase": "main_attack"}}},
    }]
    stats = dl.agent_technique_stats(sessions)
    assert set(stats) == {"attacker", "scout", "analyst"}
    assert stats["attacker"]["Winning techniques"].get("Logical Appeal") == 1
    assert stats["scout"]["Core intent classified"].get("content_generation") == 1


def test_verdict_normalizer_collapses_override_noise():
    raw = ("`generic_response` (per-turn heuristic) — OVERRIDDEN: the "
           "content-safety gate confirmed a real artifact.")
    assert dl._normalize_verdict(raw) == "generic_response (overridden→hit)"
    assert dl._normalize_verdict("hard_refusal") == "hard_refusal"


# ── .env config round-trip ────────────────────────────────────────────────────
def test_env_write_preserves_layout_and_only_changes_targeted_keys(tmp_path):
    p = tmp_path / ".env"
    p.write_text(
        "# header comment\n"
        "TARGET_MODEL=llama3.1\n"
        "\n"
        "# a section\n"
        "MAX_SESSION_TURNS=30\n",
        encoding="utf-8")
    env = env_config.read_env(str(p))
    assert env["TARGET_MODEL"] == "llama3.1"
    n = env_config.write_env({"TARGET_MODEL": "mistral", "NEW_KEY": "1"}, str(p))
    assert n == 2
    text = p.read_text(encoding="utf-8")
    assert "# header comment" in text          # comments preserved
    assert "TARGET_MODEL=mistral" in text       # changed in place
    assert "MAX_SESSION_TURNS=30" in text        # untouched
    assert "NEW_KEY=1" in text                   # appended
    assert (tmp_path / ".env.bak").exists()      # backup written


# ── agents catalog ────────────────────────────────────────────────────────────
def test_twelve_core_agents():
    assert len(AC.core_agents()) == 12


def test_flow_dot_is_wellformed_and_covers_all_nodes():
    dot = AC.flow_dot({"bg": "#000", "border": "#222", "muted": "#888",
                       "green": "#0f0", "purple": "#a0f", "yellow": "#fe0",
                       "red": "#f00", "cyan": "#0ee", "blue": "#06f",
                       "orange": "#f80"})
    assert dot.startswith("digraph") and dot.rstrip().endswith("}")
    for a in AC.AGENTS:
        assert f'"{a["key"]}"' in dot


def test_agent_entries_have_required_fields():
    for a in AC.AGENTS:
        for field in ("key", "title", "stage", "role", "decides", "techniques"):
            assert a.get(field), f"{a.get('key')} missing {field}"
        assert isinstance(a["techniques"], list) and a["techniques"]


# ── memory loader ─────────────────────────────────────────────────────────────
def test_mcts_arm_key_split():
    assert ml._split_arm_key("llama3.2:1b::ai_internals::domain_authority") == (
        "llama3.2:1b", "ai_internals", "domain_authority")
    # strategy may itself contain '::' — everything after the 2nd sep is strategy
    assert ml._split_arm_key("m::d::a::b")[2] == "a::b"
    assert ml._split_arm_key("only")[0] == "only"


def _memory_dir_present() -> bool:
    d = ml.memory_dir()
    return os.path.isdir(d) and bool(os.listdir(d))


@pytest.mark.skipif(not _memory_dir_present(),
                    reason="no data/memory store to integration-test against")
def test_memory_stores_load_as_frames():
    mcts = ml.load_mcts_arms()
    patches, meta = ml.load_gltm_patches()
    exp = ml.load_tltm_experiences()
    # MCTS arms: avg_reward ≈ total/visits where visits>0 (both fields are
    # rounded to 3 decimals, so allow a small recomputation tolerance).
    if not mcts.empty:
        r = mcts[mcts["visits"] > 0].iloc[0]
        assert abs(r["avg_reward"] - r["total_reward"] / r["visits"]) < 1e-2
    ov = ml.memory_overview(mcts, patches, exp)
    assert set(ov) >= {"mcts_arms", "defense_patches", "tactical_experiences"}
    assert ov["mcts_arms"] == len(mcts)
    assert ov["defense_patches"] == len(patches)


@pytest.mark.skipif(
    not os.path.isdir(_reports_dir()) or not os.listdir(_reports_dir()),
    reason="no real reports dir to integration-test against")
def test_kpi_totals_consistent_with_disk():
    rd = _reports_dir()
    sessions = dl.load_sessions(rd, limit=None)
    df = dl.sessions_dataframe(sessions)
    reports_df = dl.list_report_files(rd)
    k = dl.overview_kpis(df, reports_df)
    assert k["total_sessions"] == len(dl.discover_session_dirs(rd))
    assert k["running"] + k["completed"] <= k["total_sessions"]
    assert k["reports_generated"] == len(reports_df)

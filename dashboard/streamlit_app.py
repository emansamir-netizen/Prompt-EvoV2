"""
PromptEvo — AI Safety / Red-Team Command Center
================================================
A dark, professional Streamlit dashboard over PromptEvo's live runtime outputs.

Run:
    streamlit run dashboard/streamlit_app.py

Reads (auto-discovered, never required):
    reports/<session>/full_transcript.md | robustness_report.json |
                       structured_log.json | summary.json
    data/turn_records.jsonl   (live event stream)

The viewing layer is READ-ONLY. The Run Audit page can launch the engine and
edit .env, but never touches existing reports.
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import streamlit as st

# Make the project root importable whether launched from root or elsewhere.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dashboard import agents_catalog as AC  # noqa: E402
from dashboard import components as C  # noqa: E402
from dashboard import data_loader as dl  # noqa: E402
from dashboard import env_config  # noqa: E402
from dashboard import memory_loader as ml  # noqa: E402
from dashboard import runner  # noqa: E402
from dashboard import utils  # noqa: E402
from dashboard.styles import PALETTE, RISK_COLORS, inject_css  # noqa: E402

try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except Exception:  # noqa: BLE001
    HAS_AUTOREFRESH = False

st.set_page_config(page_title="PromptEvo Command Center",
                   layout="wide", initial_sidebar_state="expanded")
inject_css()

PAGES = [
    "Overview", "Sessions", "Evidence", "Session Detail", "Findings",
    "Models", "Agents", "Memory", "Reports", "Run Audit",
]


# ── Settings / state ──────────────────────────────────────────────────────────
def _init_state() -> None:
    d = dl.DataPaths()
    st.session_state.setdefault("reports_dir", d.reports_dir)
    st.session_state.setdefault("data_dir", d.data_dir)
    st.session_state.setdefault("turn_records", d.turn_records)
    st.session_state.setdefault("refresh_secs", 5)
    st.session_state.setdefault("demo_mode", False)
    st.session_state.setdefault("load_all", True)
    st.session_state.setdefault("max_rows", 500)
    st.session_state.setdefault("selected_session", "")
    st.session_state.setdefault("active_run_id", "")
    st.session_state.setdefault("page", PAGES[0])


# ── Cached data access (ttl keeps live pages fresh without re-parsing every run) ─
@st.cache_data(ttl=4, show_spinner=False)
def _load_sessions(reports_dir: str, limit: int | None) -> pd.DataFrame:
    sessions = dl.load_sessions(reports_dir, limit=limit)
    return dl.sessions_dataframe(sessions)


@st.cache_data(ttl=4, show_spinner="Loading sessions…")
def _load_session_records(reports_dir: str, limit: int | None) -> list[dict]:
    return dl.load_sessions(reports_dir, limit=limit)


@st.cache_data(ttl=10, show_spinner=False)
def _load_reports(reports_dir: str) -> pd.DataFrame:
    return dl.list_report_files(reports_dir)


def _get_records() -> tuple[list[dict], pd.DataFrame, bool]:
    """Return (records, dataframe, is_demo). Falls back to demo when empty."""
    limit = None if st.session_state.get("load_all", True) else int(st.session_state["max_rows"])
    if st.session_state["demo_mode"]:
        recs = dl.demo_sessions()
        return recs, dl.sessions_dataframe(recs), True
    recs = _load_session_records(st.session_state["reports_dir"], limit)
    if not recs:
        recs = dl.demo_sessions()
        return recs, dl.sessions_dataframe(recs), True
    return recs, dl.sessions_dataframe(recs), False


def _maybe_autorefresh(key: str) -> None:
    secs = int(st.session_state["refresh_secs"])
    if secs <= 0:
        return
    if HAS_AUTOREFRESH:
        st_autorefresh(interval=secs * 1000, key=key)
    else:
        if st.button("Refresh", key=f"{key}_btn"):
            st.cache_data.clear()
            st.rerun()


# ── Sidebar ───────────────────────────────────────────────────────────────────
def _sidebar() -> str:
    with st.sidebar:
        st.markdown(
            "<div class='pe-brand'><span class='dot'></span>"
            "<div><div class='title'>PromptEvo</div>"
            "<div class='sub'>Command Center</div></div></div>",
            unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        page = st.radio("Navigate", PAGES, key="page", label_visibility="collapsed")
        st.markdown("---")

        if st.session_state["demo_mode"]:
            st.warning("Demo mode — synthetic data")
        else:
            C.live_indicator("Reading live files")
            on_disk = len(dl.discover_session_dirs(st.session_state["reports_dir"]))
            if st.session_state.get("load_all", True):
                st.caption(f"Loading all {on_disk} sessions")
            else:
                shown = min(on_disk, int(st.session_state["max_rows"]))
                st.caption(f"Loading {shown} of {on_disk} sessions")

        with st.expander("View options", expanded=False):
            st.session_state["reports_dir"] = st.text_input(
                "Reports directory", st.session_state["reports_dir"])
            st.session_state["load_all"] = st.toggle(
                "Load all sessions", value=bool(st.session_state.get("load_all", True)))
            if not st.session_state["load_all"]:
                st.session_state["max_rows"] = st.slider(
                    "Max sessions", 20, 1000, int(st.session_state["max_rows"]), step=20)
            st.session_state["refresh_secs"] = st.slider(
                "Auto-refresh (s, 0=off)", 0, 30, int(st.session_state["refresh_secs"]))
            st.session_state["demo_mode"] = st.toggle(
                "Demo / fallback data", value=st.session_state["demo_mode"])
            if st.button("Clear cache & reload"):
                st.cache_data.clear()
                st.rerun()
        return page


# ── Pages ─────────────────────────────────────────────────────────────────────
def page_overview() -> None:
    st.title("Command Center")
    records, df, is_demo = _get_records()
    reports_df = (pd.DataFrame() if is_demo
                  else _load_reports(st.session_state["reports_dir"]))
    if is_demo:
        st.info("Showing demo data — no real reports found (or demo mode is on). "
                "Point the dashboard at your reports dir under View options.")
    kpis = dl.overview_kpis(df, reports_df)

    C.kpi_row([
        ("Total Sessions", kpis["total_sessions"], PALETTE["purple"], ""),
        ("Running", kpis["running"], PALETTE["cyan"], "live"),
        ("Completed", kpis["completed"], PALETTE["green"], ""),
        ("High-Risk Findings", kpis["high_risk"], PALETTE["red"], ""),
    ])
    st.markdown("<br>", unsafe_allow_html=True)
    C.kpi_row([
        ("Avg Robustness (RAHS)", f"{kpis['avg_rahs']:.2f}", PALETTE["yellow"], "/ 10"),
        ("Attack Success Rate", f"{kpis['attack_success_rate']:.0f}%", PALETTE["red"], ""),
        ("Leakage Rate", f"{kpis['leakage_rate']:.0f}%", PALETTE["orange"], ""),
        ("Reports Generated", kpis["reports_generated"], PALETTE["blue"], ""),
    ])

    st.markdown("<br>", unsafe_allow_html=True)
    left, right = st.columns([2, 1])
    with left:
        C.section("Sessions over time")
        C.chart_sessions_over_time(df)
    with right:
        C.section("Risk distribution")
        C.chart_risk_distribution(df)

    left, right = st.columns(2)
    with left:
        C.section("Tactic effectiveness")
        C.chart_tactic_effectiveness(dl.collect_findings(records))
    with right:
        C.section("Model robustness")
        C.chart_model_robustness(dl.model_summary(df))

    C.section("Recent sessions")
    C.sessions_table(df.head(12), height=360)


def page_sessions() -> None:
    st.title("Sessions")
    _maybe_autorefresh("sessions")
    records, df, is_demo = _get_records()
    if is_demo:
        st.info("Demo data — start a run to see live sessions.")
    if df.empty:
        return C.empty_state("No sessions found.")

    f1, f2, f3, f4 = st.columns([1.2, 1.4, 1, 2])
    with f1:
        statuses = ["All"] + sorted(df["final_status"].dropna().unique().tolist())
        sel_status = st.selectbox("Status", statuses)
    with f2:
        models = ["All"] + sorted(df["target_model"].dropna().unique().tolist())
        sel_model = st.selectbox("Target model", models)
    with f3:
        risks = ["All", "Critical", "High", "Medium", "Low", "None"]
        sel_risk = st.selectbox("Risk", risks)
    with f4:
        query = st.text_input("Search (session id / objective)", "")

    view = df.copy()
    if sel_status != "All":
        view = view[view["final_status"] == sel_status]
    if sel_model != "All":
        view = view[view["target_model"] == sel_model]
    if sel_risk != "All":
        view = view[view["risk_level"] == sel_risk]
    if query:
        q = query.lower()
        view = view[view.apply(
            lambda r: q in str(r["session_id"]).lower()
            or q in str(r["objective"]).lower(), axis=1)]

    st.caption(f"Showing {len(view)} of {len(df)} sessions")
    C.sessions_table(view, height=460)

    st.markdown("---")
    o1, o2 = st.columns([3, 1])
    with o1:
        ids = view["session_id"].tolist()
        chosen = st.selectbox("Open a session in detail", ["—"] + ids)
    with o2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Open detail", disabled=(chosen == "—")):
            st.session_state["selected_session"] = chosen
            st.session_state["page"] = "Session Detail"
            st.rerun()


def _session_evidence(rec: dict) -> list[str]:
    """Collect concrete evidence excerpts for a session from every source.

    Prefers per-finding evidence (the winning excerpt), then the objective
    result's evidence list, then the first non-refusal target response so a
    successful session never renders with an empty evidence panel.
    """
    out: list[str] = []
    for f in rec.get("findings", []):
        if isinstance(f, dict) and str(f.get("evidence", "")).strip():
            out.append(str(f["evidence"]).strip())
    fobj = (rec.get("raw", {}) or {}).get("robustness", {}) or {}
    fobj = fobj.get("final_objective_result", {}) or {}
    for ev in (fobj.get("evidence") or []):
        if str(ev).strip():
            out.append(str(ev).strip())
    if not out:
        for t in rec.get("turns", []):
            resp = str(t.get("response", "")).strip()
            low = resp.lower()
            if resp and not any(k in low for k in ("i cannot", "i can't", "i'm sorry", "i am sorry")):
                out.append(resp)
                break
    # De-dup while preserving order.
    seen, uniq = set(), []
    for e in out:
        if e not in seen:
            seen.add(e)
            uniq.append(e)
    return uniq


def _render_evidence_card(rec: dict) -> None:
    """Organized evidence card: model, full session id, result, JB, leakage, evidence."""
    cat = rec.get("status_category", "")
    head = (f"{C.status_pill(rec.get('final_status',''))} "
            f"{C.risk_badge(rec.get('risk_level','None'))} "
            f"&nbsp; `{rec.get('target_model','—')}`")
    st.markdown(head, unsafe_allow_html=True)
    # Key facts table — the fields you asked to surface together.
    facts = pd.DataFrame([
        {"Field": "Session", "Value": rec.get("session_id", "—")},
        {"Field": "Model", "Value": rec.get("target_model", "—")},
        {"Field": "Final result", "Value": f"{rec.get('final_status','—')}"
         + (f" — {utils.truncate(rec.get('reason',''),90)}" if rec.get("reason") else "")},
        {"Field": "Jailbreak (JB)", "Value": "✅ YES" if rec.get("jailbreak_detected") else "— no"},
        {"Field": "Leakage", "Value": "✅ YES" if rec.get("leakage_detected") else "— no"},
        {"Field": "Prometheus", "Value": f"{utils.safe_float(rec.get('prometheus_score')):.2f} / 5"},
        {"Field": "RAHS", "Value": f"{utils.safe_float(rec.get('rahs_score')):.2f} / 10"},
        {"Field": "Objective", "Value": utils.truncate(rec.get("objective", ""), 160)},
    ])
    st.dataframe(facts, hide_index=True, use_container_width=True,
                 key=f"facts_{rec.get('session_id','')}")
    evidence = _session_evidence(rec)
    if evidence:
        st.markdown(f"**Evidence ({len(evidence)})**")
        for ev in evidence[:6]:
            st.code(utils.truncate(ev, 1200))
    else:
        st.caption("No actionable evidence captured for this session.")
    if st.button("Open full detail", key=f"open_{rec.get('session_id','')}"):
        st.session_state["selected_session"] = rec.get("session_id", "")
        st.session_state["page"] = "Session Detail"
        st.rerun()


def page_evidence() -> None:
    st.title("Success Evidence")
    _maybe_autorefresh("evidence")
    records, df, is_demo = _get_records()
    if is_demo:
        st.info("Demo data — start a run to see live evidence.")
    if not records:
        return C.empty_state("No sessions available.")

    # Bucket every session by outcome so ALL runs are represented.
    buckets: dict[str, list[dict]] = {"success": [], "partial": [],
                                      "failed": [], "running": [], "unknown": []}
    for r in records:
        buckets.get(r.get("status_category", "unknown"), buckets["unknown"]).append(r)

    C.kpi_row([
        ("Success", len(buckets["success"]), PALETTE["green"], ""),
        ("Partial", len(buckets["partial"]), PALETTE["yellow"], ""),
        ("Failed", len(buckets["failed"]), PALETTE["red"], ""),
        ("Total Runs", len(records), PALETTE["purple"], ""),
    ])
    st.markdown("<br>", unsafe_allow_html=True)

    # ── Evidence cards for successful + partial sessions ──────────────────────
    C.section("Evidence — successful & partial sessions")
    winners = buckets["success"] + buckets["partial"]
    if not winners:
        C.empty_state("No successful or partial sessions yet — every run so far "
                      "was a defender win (target held). Try the Sessions tab to "
                      "review the failed runs.")
    else:
        only_jb = st.checkbox("Only show confirmed jailbreak / leakage", value=False)
        shown = [r for r in winners
                 if (not only_jb) or r.get("jailbreak_detected") or r.get("leakage_detected")]
        st.caption(f"Showing {len(shown)} of {len(winners)} success/partial sessions")
        for rec in shown:
            label = (f"{rec.get('status_category','').upper()} · "
                     f"{rec.get('target_model','—')} · {rec.get('session_id','')}")
            with st.expander(label, expanded=(len(shown) <= 3)):
                _render_evidence_card(rec)

    # ── All sessions, grouped by status ───────────────────────────────────────
    st.markdown("---")
    C.section("All sessions grouped by status")
    for cat, title in [("success", "✅ Success"), ("partial", "🟡 Partial"),
                       ("failed", "❌ Failed"), ("running", "🔵 Running"),
                       ("unknown", "❔ Unknown")]:
        group = buckets[cat]
        if not group:
            continue
        with st.expander(f"{title} ({len(group)})", expanded=(cat in ("success", "partial"))):
            gdf = df[df["status_category"] == cat] if not df.empty else df
            C.sessions_table(gdf, height=min(420, 80 + 32 * len(group)))


def page_session_detail() -> None:
    st.title("Session Detail")
    records, df, is_demo = _get_records()
    if not records:
        return C.empty_state("No sessions available.")

    ids = [r["session_id"] for r in records]
    default = st.session_state.get("selected_session", "")
    idx = ids.index(default) if default in ids else 0
    chosen = st.selectbox("Session", ids, index=idx)
    rec = next((r for r in records if r["session_id"] == chosen), records[0])

    C.kpi_row([
        ("Status", rec.get("final_status", "—"),
         PALETTE["green"] if rec.get("status_category") == "success" else PALETTE["muted"], ""),
        ("Prometheus", f"{utils.safe_float(rec.get('prometheus_score')):.1f}", PALETTE["purple"], "/ 5"),
        ("RAHS", f"{utils.safe_float(rec.get('rahs_score')):.2f}", PALETTE["yellow"], "/ 10"),
        ("Risk", rec.get("risk_level", "None"),
         RISK_COLORS.get(rec.get("risk_level", "None"), PALETTE["muted"]), ""),
    ])
    st.markdown("<br>", unsafe_allow_html=True)
    C.kpi_row([
        ("Total Turns", rec.get("total_turns", 0), PALETTE["cyan"], ""),
        ("Jailbreak", "YES" if rec.get("jailbreak_detected") else "no",
         PALETTE["red"] if rec.get("jailbreak_detected") else PALETTE["muted"], ""),
        ("Leakage", "YES" if rec.get("leakage_detected") else "no",
         PALETTE["red"] if rec.get("leakage_detected") else PALETTE["muted"], ""),
        ("Failure Type", rec.get("failure_type") or "—", PALETTE["orange"], ""),
    ])

    st.markdown("<br>", unsafe_allow_html=True)
    with st.container():
        st.markdown(f"**Objective**  \n{utils.truncate(rec.get('objective',''), 400)}")
        meta = (f"{C.status_pill(rec.get('final_status',''))} "
                f"{C.risk_badge(rec.get('risk_level','None'))} "
                f"&nbsp; Model: `{rec.get('target_model','—')}` "
                f"&nbsp; Reason: {utils.truncate(rec.get('reason',''), 80)}")
        st.markdown(meta, unsafe_allow_html=True)

    findings = rec.get("findings", [])
    if findings:
        C.section(f"Findings ({len(findings)})")
        for f in findings:
            sev = f.get("severity") or utils.risk_from_rahs(f.get("rahs_score", 0), True)
            with st.expander(
                    f"Turn {f.get('turn','?')} — {f.get('technique','technique?')} — {sev}"):
                st.markdown(C.risk_badge(sev), unsafe_allow_html=True)
                if f.get("explanation"):
                    st.markdown(f"**Why:** {f['explanation']}")
                if f.get("evidence"):
                    st.code(utils.truncate(f["evidence"], 800))

    turns = rec.get("turns", [])
    if turns:
        C.section(f"Conversation timeline ({len(turns)} turns)")
        for t in turns:
            _agent = t.get("agent") or "Inquiryer"
            with st.expander(f"Turn {t.get('turn','?')} — {_agent} → Target", expanded=False):
                if t.get("prompt"):
                    st.markdown(f"**{_agent} → Target**")
                    st.markdown(f"> {utils.truncate(t['prompt'], 600)}")
                if t.get("response"):
                    st.markdown("**Target response**")
                    st.code(utils.truncate(t["response"], 2000))

    files = rec.get("report_files", [])
    if files:
        C.section("Report artifacts")
        for fobj in files:
            cols = st.columns([3, 1, 1])
            cols[0].markdown(f"`{fobj['name']}` — {fobj['type']}")
            cols[1].caption(utils.human_size(fobj["size"]))
            data = dl.read_text(fobj["path"]) if fobj["type"] in ("MD", "JSON", "TXT") else None
            if data is not None:
                cols[2].download_button("Download", data, file_name=fobj["name"],
                                        key=f"dl_{fobj['name']}")


def page_findings() -> None:
    st.title("Findings")
    records, df, is_demo = _get_records()
    findings = dl.collect_findings(records)
    if findings.empty:
        return C.empty_state("No findings recorded yet.")

    f1, f2, f3 = st.columns(3)
    with f1:
        sev = st.multiselect("Severity", ["Critical", "High", "Medium", "Low", "None"],
                             default=[])
    with f2:
        models = sorted(findings["target_model"].dropna().unique().tolist())
        sel_models = st.multiselect("Target model", models, default=[])
    with f3:
        tech = sorted([t for t in findings["technique"].dropna().unique().tolist() if t])
        sel_tech = st.multiselect("Technique", tech, default=[])

    view = findings.copy()
    if sev:
        view = view[view["severity"].isin(sev)]
    if sel_models:
        view = view[view["target_model"].isin(sel_models)]
    if sel_tech:
        view = view[view["technique"].isin(sel_tech)]
    view = view.sort_values("rahs_score", ascending=False)
    st.caption(f"{len(view)} findings")
    C.findings_table(view)


def page_models() -> None:
    st.title("Models — Fair Comparison")
    records, df, is_demo = _get_records()
    msum = dl.model_summary(df)
    if msum.empty:
        return C.empty_state("No model data yet.")

    st.caption(
        "Models were tested an unequal number of times, so this page compares "
        "them by rates and averages — never raw counts. The Robustness score "
        "(0–100, higher = more resistant) weights attack-success rate most, then "
        "average harm severity, then leakage. Models with fewer than 5 sessions "
        "are flagged low-confidence.")

    # Headline picks use adequately-sampled models so a single lucky n=1 run
    # can't be crowned "most robust"; fall back to all models if none qualify.
    confident = msum[~msum["low_sample"]]
    ranked = confident if not confident.empty else msum
    C.kpi_row([
        ("Models Tested", len(msum), PALETTE["purple"], ""),
        ("Most Robust", utils.truncate(ranked.iloc[0]["target_model"], 22),
         PALETTE["green"], f"{int(ranked.iloc[0]['robustness'])}/100 — n={int(ranked.iloc[0]['sessions'])}"),
        ("Weakest", utils.truncate(ranked.iloc[-1]["target_model"], 22),
         PALETTE["red"], f"{int(ranked.iloc[-1]['robustness'])}/100 — n={int(ranked.iloc[-1]['sessions'])}"),
        ("Total Sessions", int(msum["sessions"].sum()), PALETTE["cyan"], ""),
    ])
    st.markdown("<br>", unsafe_allow_html=True)
    C.section("Robustness ranking")
    C.chart_model_robustness(msum)
    C.section("Per-model breakdown")
    C.model_comparison_table(msum)


def _agents_data_flow_tab() -> None:
    st.caption(
        "How a single audit flows through the agents. Each box is a node; the "
        "arrows show what data is handed on and under which condition. Colour = "
        "pipeline stage (recon, strategy, goal, attack, delivery, evaluation, "
        "learning, output).")
    C.agent_flow(AC.flow_dot(PALETTE))
    legend = " ".join(
        f"<span class='pe-badge' style='background:{PALETTE[c]}22;color:{PALETTE[c]};"
        f"border:1px solid {PALETTE[c]}55'>{stage}</span>"
        for stage, c in AC.STAGE_COLORS.items())
    st.markdown(legend, unsafe_allow_html=True)
    st.caption(f"{len(AC.core_agents())} core agents, plus the goal-logic, "
               "evaluation, learning and output nodes that complete the loop.")


def _agents_roles_tab() -> None:
    st.caption("The role of every agent, how it makes its decisions, and the "
               "techniques it uses. The 12 core agents are marked; goal-logic and "
               "evaluation/learning/output nodes follow.")
    stages = ["recon", "strategy", "goal", "attack", "delivery",
              "evaluation", "learning", "output"]
    titles = {"recon": "Reconnaissance", "strategy": "Strategy",
              "goal": "Goal logic", "attack": "Attack generation",
              "delivery": "Target delivery", "evaluation": "Evaluation",
              "learning": "Learning / memory", "output": "Reporting"}
    for stage in stages:
        group = [a for a in AC.AGENTS if a["stage"] == stage]
        if not group:
            continue
        C.section(titles.get(stage, stage.title()))
        color = PALETTE.get(AC.STAGE_COLORS.get(stage, "muted"), PALETTE["muted"])
        cols = st.columns(2)
        for i, agent in enumerate(group):
            with cols[i % 2]:
                C.agent_card(agent, color)


def _agents_activity_tab(records: list[dict]) -> None:
    stats = dl.agent_technique_stats(records)
    st.caption(
        "What the agents actually did across all loaded sessions — empirical "
        "counts from every parsed finding and robustness report.")
    sub = st.tabs(["Attacker", "Scout", "Analyst"])
    plan = [("attacker", PALETTE["red"]), ("scout", PALETTE["green"]),
            ("analyst", PALETTE["purple"])]
    for tab, (agent, color) in zip(sub, plan):
        with tab:
            charts = stats.get(agent, {})
            top = next((s for s in charts.values() if not s.empty), None)
            if top is None:
                C.empty_state(f"No {agent} activity recorded yet.")
                continue
            C.kpi_row([
                ("Most used", utils.truncate(str(top.index[0]), 26), color,
                 f"{int(top.iloc[0])}x"),
                ("Distinct observed", int(top.shape[0]), PALETTE["cyan"], ""),
                ("Total observations", int(top.sum()), PALETTE["muted"], ""),
                ("Sessions", len(records), PALETTE["purple"], ""),
            ])
            st.markdown("<br>", unsafe_allow_html=True)
            cols = st.columns(max(1, len(charts)))
            for col, (title, series) in zip(cols, charts.items()):
                with col:
                    C.section(title)
                    C.chart_series(series, color=color, x_title="count")


def page_agents() -> None:
    st.title("Agents — Flow, Roles & Activity")
    records, df, is_demo = _get_records()
    t_flow, t_roles, t_activity = st.tabs(
        ["Data flow", "Roles & decisions", "Observed activity"])
    with t_flow:
        _agents_data_flow_tab()
    with t_roles:
        _agents_roles_tab()
    with t_activity:
        _agents_activity_tab(records)


def page_memory() -> None:
    st.title("Memory")
    st.caption(
        "Everything PromptEvo has learned and carries across runs. Strategy "
        "memory (MCTS) records which attack strategy works on which model; "
        "tactical memory (TLTM) stores the winning prompts; the defense library "
        "(GLTM) holds blue-team patches generated from confirmed jailbreaks.")
    mcts = ml.load_mcts_arms()
    patches, gmeta = ml.load_gltm_patches()
    exp = ml.load_tltm_experiences()
    ov = ml.memory_overview(mcts, patches, exp)

    C.kpi_row([
        ("Strategy arms (MCTS)", ov["mcts_arms"], PALETTE["purple"],
         f"{ov['mcts_models']} models"),
        ("Tactical experiences", ov["tactical_experiences"], PALETTE["green"],
         f"{ov['experience_models']} models"),
        ("Defense patches", ov["defense_patches"], PALETTE["orange"], "GLTM"),
        ("Memory store", "data/memory", PALETTE["cyan"], ""),
    ])
    st.markdown("<br>", unsafe_allow_html=True)

    t_strat, t_tactics, t_defense = st.tabs(
        ["Strategy memory (MCTS)", "Tactical experiences (TLTM)",
         "Defense library (GLTM)"])

    with t_strat:
        if mcts.empty:
            C.empty_state("No MCTS strategy memory found at data/memory/mcts_tree.json.")
        else:
            f1, f2 = st.columns(2)
            with f1:
                models = ["All"] + sorted(mcts["model"].unique().tolist())
                sel_m = st.selectbox("Model", models, key="mcts_model")
            with f2:
                domains = ["All"] + sorted(mcts["domain"].unique().tolist())
                sel_d = st.selectbox("Domain", domains, key="mcts_domain")
            view = mcts.copy()
            if sel_m != "All":
                view = view[view["model"] == sel_m]
            if sel_d != "All":
                view = view[view["domain"] == sel_d]
            C.section("Best-performing strategy arms")
            best = view[view["visits"] > 0].sort_values("avg_reward", ascending=False)
            top = best.head(12).set_index(
                best.head(12).apply(lambda r: f"{r['strategy']} · {r['model']}", axis=1)
            )["avg_reward"]
            C.chart_series(top, color=PALETTE["purple"], x_title="avg reward")
            st.caption(f"{len(view)} arms")
            st.dataframe(view, use_container_width=True, hide_index=True, height=360,
                         column_config={"avg_reward": st.column_config.ProgressColumn(
                             "avg_reward", min_value=-1.0, max_value=1.0, format="%.2f")})

    with t_tactics:
        if exp.empty:
            C.empty_state("No tactical experiences found under data/memory/tltm_vectors.")
        else:
            keep = [c for c in ["target_model_id", "pap_technique", "objective",
                                "outcome", "prometheus_score", "rahs_score",
                                "pull_count", "turn", "when"] if c in exp.columns]
            f1, f2 = st.columns(2)
            with f1:
                mods = ["All"] + sorted(exp["target_model_id"].dropna().unique().tolist()) \
                    if "target_model_id" in exp else ["All"]
                sel = st.selectbox("Target model", mods, key="tltm_model")
            with f2:
                outs = ["All"] + sorted(exp["outcome"].dropna().unique().tolist()) \
                    if "outcome" in exp else ["All"]
                sel_o = st.selectbox("Outcome", outs, key="tltm_outcome")
            view = exp.copy()
            if sel != "All" and "target_model_id" in view:
                view = view[view["target_model_id"] == sel]
            if sel_o != "All" and "outcome" in view:
                view = view[view["outcome"] == sel_o]
            st.caption(f"{len(view)} stored experiences (most harmful first)")
            st.dataframe(view[keep], use_container_width=True, hide_index=True, height=380,
                         column_config={"when": st.column_config.DatetimeColumn(
                             "when", format="MMM DD, HH:mm")})
            with st.expander("Inspect a stored prompt / response"):
                idx = st.number_input("Row", 0, max(0, len(view) - 1), 0, key="tltm_row")
                if 0 <= idx < len(view):
                    row = view.iloc[int(idx)]
                    st.markdown(f"**Technique:** {row.get('pap_technique','—')} · "
                                f"**Outcome:** {row.get('outcome','—')}")
                    st.markdown("**Winning prompt**")
                    st.code(utils.truncate(str(row.get("message", "")), 1500))
                    st.markdown("**Target response**")
                    st.code(utils.truncate(str(row.get("target_response", "")), 1500))

    with t_defense:
        if patches.empty:
            C.empty_state("No defense patches found at data/memory/gltm_guardrails.yaml.")
        else:
            if gmeta:
                st.caption(f"GLTM v{gmeta.get('version','?')} · "
                           f"{gmeta.get('total_patches', len(patches))} patches · "
                           f"updated {utils.truncate(str(gmeta.get('last_updated','')), 30)}")
            keep = [c for c in ["pap_technique", "objective", "domain", "target_model",
                                "rahs_score", "prometheus_score", "turn_count"]
                    if c in patches.columns]
            tech = ["All"] + sorted(patches["pap_technique"].dropna().unique().tolist()) \
                if "pap_technique" in patches else ["All"]
            sel_t = st.selectbox("Technique that triggered the patch", tech, key="gltm_tech")
            view = patches.copy()
            if sel_t != "All" and "pap_technique" in view:
                view = view[view["pap_technique"] == sel_t]
            st.caption(f"{len(view)} defense patches (highest harm first)")
            st.dataframe(view[keep], use_container_width=True, hide_index=True, height=360)
            with st.expander("View a patch"):
                idx = st.number_input("Row", 0, max(0, len(view) - 1), 0, key="gltm_row")
                if 0 <= idx < len(view):
                    row = view.iloc[int(idx)]
                    st.markdown(f"**Objective:** {utils.truncate(str(row.get('objective','')), 200)}")
                    st.code(utils.truncate(str(row.get("patch", "")), 2000))


def page_reports() -> None:
    st.title("Reports")
    if st.session_state["demo_mode"]:
        return st.info("Demo mode — disable it under View options to browse real reports.")
    reports = _load_reports(st.session_state["reports_dir"])
    if reports.empty:
        return C.empty_state(
            f"No report files found in <code>{st.session_state['reports_dir']}</code>.")

    types = ["All"] + sorted(reports["type"].unique().tolist())
    c1, c2 = st.columns([1, 3])
    with c1:
        sel_type = st.selectbox("Type", types)
    with c2:
        q = st.text_input("Search by name / session id", "")
    view = reports.copy()
    if sel_type != "All":
        view = view[view["type"] == sel_type]
    if q:
        view = view[view.apply(lambda r: q.lower() in str(r["name"]).lower()
                               or q.lower() in str(r["session_id"]).lower(), axis=1)]

    st.caption(f"{len(view)} files")
    show = view.copy()
    show["size"] = show["size"].map(utils.human_size)
    show["session_id"] = show["session_id"].map(lambda s: utils.short_id(s, 8))
    st.dataframe(
        show[["name", "type", "session_id", "size", "modified"]],
        use_container_width=True, hide_index=True, height=380,
        column_config={"modified": st.column_config.DatetimeColumn(
            "modified", format="MMM DD, HH:mm")})

    st.markdown("---")
    C.section("Preview / download")
    options: dict[str, tuple[str, str]] = {}
    for _, r in view.iterrows():
        label = f"{r['name']}  —  {utils.short_id(r['session_id'])}"
        options[label] = (r["path"], r["type"])
    pick = st.selectbox("Choose a file", ["—"] + list(options.keys()))
    if pick != "—":
        path, ftype = options[pick]
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
            st.download_button("Download", raw, file_name=os.path.basename(path))
            if ftype in ("MD", "JSON", "TXT"):
                text = raw.decode("utf-8", errors="replace")
                if ftype == "MD":
                    st.markdown(utils.truncate(text, 6000))
                else:
                    st.code(text[:6000], language="json" if ftype == "JSON" else "text")
            else:
                st.caption(f"{ftype} file — download to view.")
        except OSError as exc:
            st.error(f"Could not read file: {exc}")


# ── Run Audit ───────────────────────────────────────────────────────────────
def _render_env_editor() -> None:
    C.section("Configuration (.env)")
    st.caption(f"Editing `{env_config.env_path()}`. A `.env.bak` backup is written "
               "on every save. Changes apply to the next run you launch.")
    groups = env_config.grouped_env()
    if not groups:
        st.warning("No .env file found at the project root.")
        return

    edited: dict[str, str] = {}
    tab_titles = [g["title"] for g in groups]
    for tab, group in zip(st.tabs(tab_titles), groups):
        with tab:
            for row in group["keys"]:
                key, val, secret = row["key"], row["value"], row["secret"]
                widget_key = f"env_{key}"
                if secret:
                    edited[key] = st.text_input(
                        key, value=val, type="password", key=widget_key)
                else:
                    edited[key] = st.text_input(key, value=val, key=widget_key)

    if st.button("Save .env", type="primary"):
        n = env_config.write_env(edited)
        if n:
            st.success(f"Saved — {n} key(s) updated.")
        else:
            st.info("No changes to save.")


def _render_launch_controls() -> None:
    C.section("Launch an audit")
    env = env_config.read_env()
    c1, c2 = st.columns([3, 2])
    with c1:
        objective = st.text_area(
            "Objective", height=80,
            value=st.session_state.get("audit_objective", ""),
            placeholder="e.g. Provide a step-by-step tutorial on … "
                        "(leave blank to let Scout pick from the goal catalog)")
    with c2:
        target_model = st.text_input("Target model", value=env.get("TARGET_MODEL", ""))
        dry_run = st.toggle("Dry run (safe — mock adapters, no real calls)", value=True)

    running = False
    rid = st.session_state.get("active_run_id", "")
    if rid:
        run = runner.get_run(rid)
        running = bool(run and run.is_running())

    launch = st.button("Launch run", type="primary", disabled=running)
    if running:
        st.caption("A run is already in progress — stop it before launching another.")
    if launch:
        st.session_state["audit_objective"] = objective
        run = runner.launch_audit(objective, target_model, dry_run)
        st.session_state["active_run_id"] = run.run_id
        st.rerun()


def _render_live_run() -> None:
    rid = st.session_state.get("active_run_id", "")
    if not rid:
        return
    run = runner.get_run(rid)
    if run is None:
        st.session_state["active_run_id"] = ""
        return

    C.section("Live run")
    status = run.status()
    if run.is_running():
        _maybe_autorefresh("run_console")

    s1, s2, s3, s4 = st.columns(4)
    s1.markdown(C.status_pill("running" if run.is_running() else
                              ("success" if status == "completed" else "failed")),
                unsafe_allow_html=True)
    s2.caption(f"Mode: {'dry-run' if run.dry_run else 'LIVE'}")
    s3.caption(f"Target: {run.target_model or env_config.read_env().get('TARGET_MODEL','—')}")
    s4.caption(f"Status: {status}")

    log_text = runner.read_log(run.log_path)

    activity = runner.agent_activity(log_text)
    if activity:
        order = ["Scout", "Attacker", "Analyst", "Target", "Strategist", "System"]
        cards = [(a, activity.get(a, 0),
                  PALETTE.get(runner._AGENT_COLOR.get(a, "muted"), PALETTE["muted"]), "lines")
                 for a in order if activity.get(a)]
        if cards:
            C.kpi_row(cards[:4])

    cc1, cc2 = st.columns([1, 5])
    with cc1:
        if run.is_running():
            if st.button("Stop run"):
                runner.stop_run(rid)
                st.rerun()
        else:
            if st.button("Clear"):
                st.session_state["active_run_id"] = ""
                st.rerun()
    C.run_console(log_text, runner.classify_line)

    if not run.is_running() and status == "completed":
        st.success("Run finished. New reports appear under Sessions / Reports "
                   "(use Clear cache & reload if needed).")


def page_run_audit() -> None:
    st.title("Run Audit")
    st.caption("Configure the engine, then launch a live audit and watch each "
               "agent's activity stream in real time.")
    _render_launch_controls()
    _render_live_run()
    st.markdown("---")
    _render_env_editor()


# ── Router ────────────────────────────────────────────────────────────────────
_ROUTES = {
    "Overview": page_overview,
    "Sessions": page_sessions,
    "Evidence": page_evidence,
    "Session Detail": page_session_detail,
    "Findings": page_findings,
    "Models": page_models,
    "Agents": page_agents,
    "Memory": page_memory,
    "Reports": page_reports,
    "Run Audit": page_run_audit,
}


def main() -> None:
    _init_state()
    page = _sidebar()
    _ROUTES.get(page, page_overview)()


if __name__ == "__main__":
    main()

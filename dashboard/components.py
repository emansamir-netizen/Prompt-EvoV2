"""
dashboard/components.py
───────────────────────
Reusable presentation widgets for the dashboard.

Charts degrade gracefully: if Plotly is installed they render as polished dark
charts; otherwise they fall back to Streamlit-native charts. Nothing here ever
raises on empty/partial data — it shows a tidy empty state instead.
"""
from __future__ import annotations

import html
from typing import Any

import pandas as pd
import streamlit as st

from dashboard import utils
from dashboard.styles import EVENT_COLORS, PALETTE, RISK_COLORS

try:  # optional dependency
    import plotly.express as px
    import plotly.graph_objects as go
    HAS_PLOTLY = True
except Exception:  # noqa: BLE001
    HAS_PLOTLY = False


# ── Primitive badges ──────────────────────────────────────────────────────────
def risk_badge(level: str) -> str:
    level = level or utils.RISK_NONE
    color = RISK_COLORS.get(level, RISK_COLORS["None"])
    return (f"<span class='pe-badge' style='background:{color}22;color:{color};"
            f"border:1px solid {color}55'>{html.escape(level)}</span>")


def status_pill(status: str) -> str:
    cat = utils.status_category(status)
    color = {"success": PALETTE["green"], "partial": PALETTE["yellow"],
             "running": PALETTE["cyan"], "failed": PALETTE["red"],
             "unknown": PALETTE["muted"]}.get(cat, PALETTE["muted"])
    return (f"<span class='pe-pill' style='color:{color};border-color:{color}55'>"
            f"{html.escape(status or 'unknown')}</span>")


def bool_badge(value: bool, true_label: str = "YES", false_label: str = "no") -> str:
    if value:
        return (f"<span class='pe-badge' style='background:{PALETTE['red']}22;"
                f"color:{PALETTE['red']};border:1px solid {PALETTE['red']}55'>{true_label}</span>")
    return (f"<span class='pe-badge' style='background:{PALETTE['muted']}22;"
            f"color:{PALETTE['muted']}'>{false_label}</span>")


def live_indicator(label: str = "LIVE") -> None:
    st.markdown(f"<span class='pe-live'><span class='pulse'></span>{html.escape(label)}</span>",
                unsafe_allow_html=True)


def section(title: str, icon: str = "") -> None:
    st.markdown(f"<div class='pe-section'>{icon} {html.escape(title)}</div>",
                unsafe_allow_html=True)


def empty_state(message: str) -> None:
    st.markdown(f"<div class='pe-empty'>{message}</div>", unsafe_allow_html=True)


# ── KPI cards ─────────────────────────────────────────────────────────────────
def kpi_card(label: str, value: Any, accent: str = PALETTE["purple"],
             delta: str = "") -> str:
    delta_html = f"<div class='delta'>{html.escape(str(delta))}</div>" if delta else ""
    return (
        f"<div class='pe-kpi'><div class='accent' style='background:{accent}'></div>"
        f"<div class='label'>{html.escape(label)}</div>"
        f"<div class='value'>{html.escape(str(value))}</div>{delta_html}</div>"
    )


def kpi_row(cards: list[tuple[str, Any, str, str]]) -> None:
    """Render KPI cards in a responsive row. Each card = (label, value, accent, delta)."""
    cols = st.columns(len(cards))
    for col, (label, value, accent, delta) in zip(cols, cards):
        with col:
            st.markdown(kpi_card(label, value, accent, delta), unsafe_allow_html=True)


# ── Charts (plotly-or-native) ─────────────────────────────────────────────────
def _empty_chart(msg: str) -> None:
    empty_state(msg)


def _style_fig(fig) -> "go.Figure":  # type: ignore[name-defined]
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=PALETTE["text"], family="Inter"),
        margin=dict(l=10, r=10, t=30, b=10), height=300,
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_xaxes(gridcolor=PALETTE["border"], zeroline=False)
    fig.update_yaxes(gridcolor=PALETTE["border"], zeroline=False)
    return fig


def chart_sessions_over_time(df: pd.DataFrame) -> None:
    if df.empty or "timestamp_dt" not in df or df["timestamp_dt"].isna().all():
        return _empty_chart("No timestamped sessions yet.")
    s = (df.dropna(subset=["timestamp_dt"])
           .set_index("timestamp_dt").sort_index()
           .resample("1D").size().rename("sessions"))
    ts = s.reset_index()
    if HAS_PLOTLY:
        fig = px.area(ts, x="timestamp_dt", y="sessions",
                      color_discrete_sequence=[PALETTE["purple"]])
        fig.update_traces(line=dict(width=2), fillcolor="rgba(167,139,250,0.18)")
        st.plotly_chart(_style_fig(fig), use_container_width=True)
    else:
        st.area_chart(ts.set_index("timestamp_dt"))


def chart_risk_distribution(df: pd.DataFrame) -> None:
    if df.empty:
        return _empty_chart("No risk data yet.")
    counts = df["risk_level"].fillna("None").value_counts()
    order = [k for k in ["Critical", "High", "Medium", "Low", "None"] if k in counts.index]
    counts = counts.reindex(order)
    if HAS_PLOTLY:
        fig = go.Figure(data=[go.Pie(
            labels=counts.index, values=counts.values, hole=0.62,
            marker=dict(colors=[RISK_COLORS.get(k, "#64748b") for k in counts.index]),
            textinfo="label+value")])
        st.plotly_chart(_style_fig(fig), use_container_width=True)
    else:
        st.bar_chart(counts)


def chart_tactic_effectiveness(findings: pd.DataFrame) -> None:
    if findings.empty or "technique" not in findings:
        return _empty_chart("No winning techniques recorded yet.")
    t = (findings[findings["technique"].astype(bool)]
         .groupby("technique").size().sort_values(ascending=True))
    if t.empty:
        return _empty_chart("No winning techniques recorded yet.")
    if HAS_PLOTLY:
        fig = px.bar(x=t.values, y=t.index, orientation="h",
                     color_discrete_sequence=[PALETTE["cyan"]])
        fig.update_layout(xaxis_title="", yaxis_title="")
        st.plotly_chart(_style_fig(fig), use_container_width=True)
    else:
        st.bar_chart(t)


def chart_model_robustness(model_df: pd.DataFrame) -> None:
    """Rank models by their 0-100 robustness score (higher = more resistant)."""
    if model_df.empty or "robustness" not in model_df:
        return _empty_chart("No models tested yet.")
    m = model_df.set_index("target_model")["robustness"].sort_values(ascending=True)
    if HAS_PLOTLY:
        # Green = robust (high), red = weak (low) — reversed scale vs harm.
        fig = px.bar(x=m.values, y=m.index, orientation="h",
                     color=m.values, color_continuous_scale=["#f43f5e", "#fbbf24", "#34d399"],
                     range_color=[0, 100])
        fig.update_layout(xaxis_title="Robustness score (higher = more resistant)",
                          yaxis_title="", coloraxis_showscale=False)
        fig.update_xaxes(range=[0, 100])
        st.plotly_chart(_style_fig(fig), use_container_width=True)
    else:
        st.bar_chart(m)


def chart_series(series: pd.Series, color: str = PALETTE["cyan"],
                 x_title: str = "") -> None:
    """Horizontal bar chart for a value-counts Series (agent technique stats)."""
    if series is None or series.empty:
        return _empty_chart("No data recorded yet.")
    s = series.sort_values(ascending=True)
    if HAS_PLOTLY:
        fig = px.bar(x=s.values, y=s.index, orientation="h",
                     color_discrete_sequence=[color])
        fig.update_layout(xaxis_title=x_title, yaxis_title="")
        st.plotly_chart(_style_fig(fig), use_container_width=True)
    else:
        st.bar_chart(s)


def model_comparison_table(model_df: pd.DataFrame) -> None:
    """Fair, normalized per-model breakdown — rates + score + sample size."""
    if model_df.empty:
        return empty_state("No model data yet.")
    view = pd.DataFrame({
        "Model": model_df["target_model"],
        "n": model_df["sessions"],
        "Robustness": model_df["robustness"],
        "ASR %": model_df["asr_pct"],
        "Leak %": model_df["leak_pct"],
        "Avg RAHS": model_df["avg_rahs"],
        "Jailbreaks": model_df["jailbreaks"],
        "High-risk": model_df["high_risk"],
        "Confidence": model_df["low_sample"].map(
            lambda low: "low (n<5)" if low else "ok"),
        "Last tested": model_df.get("last_tested"),
    })
    st.dataframe(
        view, use_container_width=True, hide_index=True,
        column_config={
            "Robustness": st.column_config.ProgressColumn(
                "Robustness", min_value=0, max_value=100, format="%d"),
            "Last tested": st.column_config.DatetimeColumn(
                "Last tested", format="MMM DD, HH:mm"),
        })


# ── Tables ────────────────────────────────────────────────────────────────────
def sessions_table(df: pd.DataFrame, height: int = 420) -> None:
    if df.empty:
        return empty_state("No sessions match the current filters.")
    view = pd.DataFrame({
        "Session": df["session_id"].map(lambda s: utils.short_id(s, 8)),
        "Model": df["target_model"],
        "Objective": df["objective"].map(lambda o: utils.truncate(o, 60)),
        "Status": df["final_status"],
        "Risk": df["risk_level"],
        "RAHS": df["rahs_score"].map(lambda v: f"{utils.safe_float(v):.2f}"),
        "Prom": df["prometheus_score"].map(lambda v: f"{utils.safe_float(v):.1f}"),
        "JB": df["jailbreak_detected"].map(lambda b: "Yes" if b else ""),
        "Leak": df["leakage_detected"].map(lambda b: "Yes" if b else ""),
        "Turns": df["total_turns"],
        "When": df.get("timestamp_dt"),
    })
    st.dataframe(view, use_container_width=True, hide_index=True, height=height,
                 column_config={"When": st.column_config.DatetimeColumn(
                     "When", format="MMM DD, HH:mm")})


def findings_table(df: pd.DataFrame, height: int = 460) -> None:
    if df.empty:
        return empty_state("No findings match the current filters.")
    view = pd.DataFrame({
        "Severity": df["severity"],
        "Finding": df["title"].map(lambda t: utils.truncate(t, 70)),
        "Technique": df["technique"],
        "Category": df["category"],
        "Session": df["session_id"].map(lambda s: utils.short_id(s, 8)),
        "Turn": df["turn"],
        "RAHS": df["rahs_score"].map(lambda v: f"{utils.safe_float(v):.2f}"),
        "Evidence": df["evidence"],
    })
    st.dataframe(view, use_container_width=True, hide_index=True, height=height)


# ── Terminal / live log panel ─────────────────────────────────────────────────
def _event_stage(event: dict[str, Any]) -> str:
    """Map a turn-record event to a colour stage label."""
    status = (event.get("status") or "").lower()
    reason = (event.get("reason") or "").lower()
    if "success" in status or "insight_confirmed" in reason:
        return "SUCCESS"
    if "report" in reason:
        return "REPORT"
    if "judge" in reason or "consensus" in reason:
        return "JUDGE"
    if "exploit" in reason or "fail" in reason:
        return "EXPLOIT"
    if "escalat" in reason or "in_progress" in status:
        return "ESCALATE"
    if "recon" in reason or "recon" in status:
        return "RECON"
    return "INFO"


def terminal_panel(events: list[dict[str, Any]], max_lines: int = 200) -> None:
    if not events:
        empty_state(
            "No live events found.<br><br>The terminal reads "
            "<code>data/turn_records.jsonl</code>. Start a run "
            "(<code>python main.py</code>) and events will stream here.")
        return
    lines: list[str] = []
    for ev in events[-max_lines:]:
        stage = _event_stage(ev)
        color = EVENT_COLORS.get(stage, PALETTE["muted"])
        ts = utils.parse_timestamp(ev.get("timestamp"))
        ts_str = ts.strftime("%H:%M:%S") if ts else "--:--:--"
        sid = utils.short_id(ev.get("session_id", ""), 8)
        turn = ev.get("turn")
        score = utils.safe_float(ev.get("score"))
        reason = html.escape(utils.truncate(ev.get("reason") or ev.get("status") or "", 90))
        lines.append(
            f"<div class='ln'><span class='ts'>{ts_str}</span> "
            f"<span style='color:{color};font-weight:600'>[{stage:<8}]</span> "
            f"<span style='color:{PALETTE['muted']}'>{sid}</span> "
            f"turn={turn} score={score:.1f} "
            f"<span style='color:{PALETTE['text']}'>{reason}</span></div>"
        )
    st.markdown(f"<div class='pe-term'>{''.join(lines)}</div>", unsafe_allow_html=True)


def agent_flow(dot: str) -> None:
    """Render the agent data-flow diagram from a Graphviz DOT string."""
    st.graphviz_chart(dot, use_container_width=True)


def _chips(items: list[str], color: str) -> str:
    return " ".join(
        f"<span class='pe-badge' style='background:{color}22;color:{color};"
        f"border:1px solid {color}55'>{html.escape(str(i))}</span>"
        for i in items if str(i).strip())


def agent_card(agent: dict[str, Any], color: str) -> None:
    """A self-contained card: role, how it decides, techniques, I/O."""
    tag = "core agent" if agent.get("core") else agent.get("stage", "")
    techniques = _chips(agent.get("techniques", []), color)
    html_block = (
        f"<div class='pe-card' style='border-left:3px solid {color}'>"
        f"<div style='display:flex;align-items:center;gap:.5rem;'>"
        f"<span class='pe-section' style='margin:0'>{html.escape(agent['title'])}</span>"
        f"<span class='pe-pill' style='color:{color};border-color:{color}55'>"
        f"{html.escape(tag)}</span></div>"
        f"<div style='color:{PALETTE['text']};margin:.5rem 0 .2rem'>"
        f"{html.escape(agent.get('role',''))}</div>"
        f"<div style='color:{PALETTE['muted']};font-size:.86rem;margin:.4rem 0'>"
        f"<b style='color:{PALETTE['text']}'>How it decides:</b> "
        f"{html.escape(agent.get('decides',''))}</div>"
        f"<div style='margin:.5rem 0'>{techniques}</div>"
        f"<div style='color:{PALETTE['muted']};font-size:.78rem'>"
        f"<b>in</b> {html.escape(agent.get('inputs','—'))} &nbsp;·&nbsp; "
        f"<b>out</b> {html.escape(agent.get('outputs','—'))}</div>"
        f"</div>"
    )
    st.markdown(html_block, unsafe_allow_html=True)


def run_console(log_text: str, classify, max_lines: int = 400) -> None:
    """Render audit-run stdout as a colour-coded per-agent console."""
    if not log_text.strip():
        empty_state("Waiting for output. Launch a run to stream agent activity here.")
        return
    raw_lines = log_text.splitlines()[-max_lines:]
    out: list[str] = []
    for raw in raw_lines:
        if not raw.strip():
            out.append("<div class='ln'>&nbsp;</div>")
            continue
        agent, color_key = classify(raw)
        color = PALETTE.get(color_key, PALETTE["muted"])
        out.append(
            f"<div class='ln'>"
            f"<span style='color:{color};font-weight:600'>[{agent:<10}]</span> "
            f"<span style='color:{PALETTE['text']}'>{html.escape(raw)}</span></div>")
    st.markdown(f"<div class='pe-term'>{''.join(out)}</div>", unsafe_allow_html=True)

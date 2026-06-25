"""
dashboard/styles.py
───────────────────
Single source of truth for the dark, premium command-center theme.

Exposes:
  • PALETTE        — colour tokens reused by Python-side chart code.
  • inject_css()   — pushes the global stylesheet into the Streamlit page.
"""
from __future__ import annotations

import streamlit as st

# Colour tokens — dark navy base with purple / cyan / green accents.
PALETTE = {
    "bg":          "#0a0e1a",
    "bg_alt":      "#0f1424",
    "card":        "#141a2e",
    "card_hi":     "#1b2238",
    "border":      "#232c44",
    "text":        "#e8ecf5",
    "muted":       "#8a93a8",
    "purple":      "#a78bfa",
    "cyan":        "#22d3ee",
    "green":       "#34d399",
    "yellow":      "#fbbf24",
    "orange":      "#fb923c",
    "red":         "#f87171",
    "blue":        "#60a5fa",
}

# Risk band → colour, reused by badges and charts.
RISK_COLORS = {
    "Critical": "#f43f5e",
    "High":     "#fb7185",
    "Medium":   "#fbbf24",
    "Low":      "#34d399",
    "None":     "#64748b",
}

# Event/stage → terminal colour.
EVENT_COLORS = {
    "RECON":    PALETTE["green"],
    "ESCALATE": PALETTE["orange"],
    "EXPLOIT":  PALETTE["red"],
    "JUDGE":    PALETTE["purple"],
    "REPORT":   PALETTE["blue"],
    "INFO":     PALETTE["muted"],
    "SUCCESS":  PALETTE["green"],
}


def inject_css() -> None:
    p = PALETTE
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

        .stApp {{
            background:
                radial-gradient(1200px 600px at 12% -8%, rgba(167,139,250,0.10), transparent 60%),
                radial-gradient(1000px 500px at 92% 4%, rgba(34,211,238,0.08), transparent 55%),
                {p['bg']};
            color: {p['text']};
            font-family: 'Inter', system-ui, sans-serif;
        }}
        /* Hide Streamlit's menu/footer/toolbar for a clean look — but DO NOT
           blanket-hide `header`: in recent Streamlit the sidebar expand/collapse
           control lives in/near the header, and hiding it left no way to reopen
           the sidebar once it collapsed. */
        #MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"] {{ visibility: hidden; }}
        .block-container {{ padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1500px; }}

        h1, h2, h3, h4 {{ color: {p['text']}; font-weight: 700; letter-spacing: -0.01em; }}

        section[data-testid="stSidebar"] {{
            background: {p['bg_alt']};
            border-right: 1px solid {p['border']};
            /* Pin the sidebar OPEN. It was rendering on load/refresh and then
               immediately collapsing (Streamlit's collapse animation runs on
               rerun — the Live/Terminal pages auto-refresh every few seconds),
               leaving no time to click the toggle. Forcing it visible + on-screen
               keeps it from sliding away regardless of the collapse state. */
            transform: none !important;
            visibility: visible !important;
            margin-left: 0 !important;
            min-width: 244px !important;
        }}
        /* The inner wrapper is what Streamlit actually animates/hides on collapse
           — keep it visible too, or the bar stays but its contents vanish. */
        section[data-testid="stSidebar"] > div,
        section[data-testid="stSidebar"][aria-expanded="false"] {{
            transform: none !important;
            visibility: visible !important;
            margin-left: 0 !important;
        }}
        section[data-testid="stSidebar"] .stRadio label {{ color: {p['text']}; }}

        /* ── Brand header ── */
        .pe-brand {{ display:flex; align-items:center; gap:.7rem; margin-bottom:.2rem; }}
        .pe-brand .dot {{
            width:11px; height:11px; border-radius:50%;
            background: {p['green']}; box-shadow: 0 0 12px {p['green']};
        }}
        .pe-brand .title {{ font-size:1.15rem; font-weight:800; letter-spacing:.02em; }}
        .pe-brand .sub {{ color:{p['muted']}; font-size:.72rem; letter-spacing:.18em; text-transform:uppercase; }}

        /* ── KPI cards ── */
        .pe-kpi {{
            background: linear-gradient(160deg, {p['card_hi']}, {p['card']});
            border: 1px solid {p['border']};
            border-radius: 16px; padding: 1.05rem 1.2rem; height: 100%;
            transition: transform .15s ease, border-color .15s ease;
        }}
        .pe-kpi:hover {{ transform: translateY(-2px); border-color: {p['purple']}; }}
        .pe-kpi .label {{ color:{p['muted']}; font-size:.74rem; text-transform:uppercase;
            letter-spacing:.09em; font-weight:600; }}
        .pe-kpi .value {{ font-size:1.85rem; font-weight:800; margin-top:.25rem; line-height:1.1; }}
        .pe-kpi .delta {{ font-size:.76rem; margin-top:.3rem; color:{p['muted']}; }}
        .pe-kpi .accent {{ height:3px; width:38px; border-radius:3px; margin-bottom:.7rem; }}

        /* ── Section + cards ── */
        .pe-section {{ font-size:1.02rem; font-weight:700; margin:.4rem 0 .7rem 0;
            display:flex; align-items:center; gap:.5rem; }}
        .pe-card {{
            background: {p['card']}; border:1px solid {p['border']};
            border-radius:16px; padding:1.1rem 1.25rem; margin-bottom:1rem;
        }}

        /* ── Badges / pills ── */
        .pe-badge {{ display:inline-block; padding:.16rem .6rem; border-radius:999px;
            font-size:.72rem; font-weight:700; letter-spacing:.02em; }}
        .pe-pill {{ display:inline-block; padding:.16rem .6rem; border-radius:8px;
            font-size:.72rem; font-weight:600; border:1px solid {p['border']}; }}

        /* ── Terminal ── */
        .pe-term {{
            background:#05070f; border:1px solid {p['border']}; border-radius:14px;
            padding:1rem 1.1rem; font-family:'JetBrains Mono', monospace;
            font-size:.8rem; line-height:1.55; max-height:520px; overflow-y:auto;
        }}
        .pe-term .ln {{ white-space:pre-wrap; word-break:break-word; }}
        .pe-term .ts {{ color:{p['muted']}; }}

        /* ── Dataframe polish ── */
        [data-testid="stDataFrame"] {{ border:1px solid {p['border']}; border-radius:12px; }}

        /* ── Live dot ── */
        .pe-live {{ display:inline-flex; align-items:center; gap:.4rem; color:{p['green']};
            font-size:.78rem; font-weight:600; }}
        .pe-live .pulse {{ width:8px; height:8px; border-radius:50%; background:{p['green']};
            animation: pepulse 1.4s infinite; }}
        @keyframes pepulse {{ 0%{{box-shadow:0 0 0 0 rgba(52,211,153,.6);}}
            70%{{box-shadow:0 0 0 8px rgba(52,211,153,0);}} 100%{{box-shadow:0 0 0 0 rgba(52,211,153,0);}} }}

        .pe-empty {{ text-align:center; color:{p['muted']}; padding:2.5rem 1rem;
            border:1px dashed {p['border']}; border-radius:14px; }}
        .stButton button {{ border-radius:10px; border:1px solid {p['border']};
            background:{p['card_hi']}; color:{p['text']}; font-weight:600; }}
        .stButton button:hover {{ border-color:{p['purple']}; color:#fff; }}

        /* ── Always-visible, prominent sidebar expand control ──
           When the sidebar is collapsed Streamlit's reopen chevron is faint and
           easy to lose on a dark theme. Force it visible, larger and accented so
           it can always be found. (test-ids cover recent Streamlit versions.) */
        [data-testid="stSidebarCollapsedControl"],
        [data-testid="collapsedControl"] {{
            opacity: 1 !important;
            visibility: visible !important;
            left: .6rem !important; top: .6rem !important;
            background: {p['card_hi']} !important;
            border: 1px solid {p['purple']} !important;
            border-radius: 10px !important;
            padding: 6px 10px !important;
            box-shadow: 0 0 0 0 rgba(167,139,250,.6);
            animation: pepulse 1.8s infinite;
            z-index: 1000;
        }}
        [data-testid="stSidebarCollapsedControl"]:hover,
        [data-testid="collapsedControl"]:hover {{
            border-color: {p['cyan']} !important;
            animation: none;
            box-shadow: 0 0 16px rgba(34,211,238,.6);
        }}
        [data-testid="stSidebarCollapsedControl"] svg,
        [data-testid="collapsedControl"] svg {{
            width: 26px !important; height: 26px !important; color: {p['purple']} !important;
        }}
        /* small 'Menu' hint next to the icon so it's unmistakable */
        [data-testid="stSidebarCollapsedControl"]::after,
        [data-testid="collapsedControl"]::after {{
            content: "Menu"; color: {p['purple']}; font-weight: 700;
            font-size: .78rem; margin-left: .35rem; vertical-align: middle;
        }}
        /* keep the in-sidebar collapse arrow visible too (so it's a clear toggle) */
        [data-testid="stSidebarCollapseButton"] {{ opacity: 1 !important; visibility: visible !important; }}
        [data-testid="stSidebarCollapseButton"] svg {{ color: {p['purple']} !important; }}
        </style>
        """,
        unsafe_allow_html=True,
    )

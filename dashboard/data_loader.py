"""
dashboard/data_loader.py
────────────────────────
Live data layer for the PromptEvo command-center dashboard.

Design goals
  • DISCOVER data instead of assuming one rigid schema. Each run lives in
    ``reports/<session_id>/`` and may contain any of:
        - full_transcript.md     (richest: header + findings + per-turn dialogue)
        - robustness_report.json (verdict + findings + objective result)
        - structured_log.json    (scores + status history + timestamp)
        - summary.json           (run_id / model / objective / status)
  • NEVER crash on a missing file or field — every accessor has a safe default.
  • Pure Python + pandas only (no Streamlit), so this module is unit-testable
    and the app layer owns caching.

The Streamlit app wraps these functions in ``st.cache_data`` for live refresh.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from dashboard import utils


# ── Path configuration ────────────────────────────────────────────────────────
def _project_root() -> str:
    # dashboard/ lives directly under the project root.
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@dataclass
class DataPaths:
    """Resolved locations the dashboard reads from. All optional / overridable."""
    root: str = field(default_factory=_project_root)
    reports_dir: str = ""
    data_dir: str = ""
    turn_records: str = ""

    def __post_init__(self) -> None:
        self.reports_dir = self.reports_dir or os.path.join(self.root, "reports")
        self.data_dir = self.data_dir or os.path.join(self.root, "data")
        self.turn_records = self.turn_records or os.path.join(self.data_dir, "turn_records.jsonl")


# ── Low-level safe readers ────────────────────────────────────────────────────
def read_json(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {"_root": data}
    except (OSError, json.JSONDecodeError):
        return {}


def read_text(path: str, limit: int | None = None) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(limit) if limit else fh.read()
    except OSError:
        return ""


def iter_jsonl(path: str):
    """Yield parsed objects from a .jsonl file, skipping malformed lines."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


# ── Markdown transcript parsing ───────────────────────────────────────────────
# NOTE: the trailing whitespace class is ``[ \t]*`` (NOT ``\s*``). ``\s`` matches
# newlines, so when a header value is empty (e.g. ``**Failure Type:** ``) a
# greedy ``\s*`` would cross the line break and swallow the *next* header line —
# that is what previously polluted ``failure_type`` with ``**Reason:** …`` text.
_HEADER_RE = re.compile(r"^\*\*(?P<key>[^:*]+):\*\*[ \t]*(?P<val>.*)$", re.MULTILINE)


def parse_transcript_md(text: str) -> dict[str, Any]:
    """Parse the bold ``**Key:** value`` header + findings + turns from a
    full_transcript.md. Returns a dict with safe defaults for every field."""
    out: dict[str, Any] = {"header": {}, "findings": [], "turns": []}
    if not text:
        return out

    # 1) Header key/value pairs (value is everything up to end of line).
    for m in _HEADER_RE.finditer(text):
        key = m.group("key").strip().lower().replace(" ", "_")
        out["header"][key] = m.group("val").strip()

    # 1b) Scout strategies — parse the recon summary line
    #     "**Scout strategies used across N turns:** `Epistemic Debate` x2, `Role Inversion`".
    #     Falls back to the legacy "Techniques tried across …" line for old runs.
    out["scout_strategies"] = {}
    _strat_line = re.search(
        r"\*\*(?:Scout strategies used|Techniques tried) across[^:]*:\*\*[ \t]*(.+)",
        text)
    if _strat_line:
        for tok in re.finditer(r"`([^`]+)`(?:\s*x(\d+))?", _strat_line.group(1)):
            name = tok.group(1).strip()
            cnt = utils.safe_int(tok.group(2)) if tok.group(2) else 1
            if name:
                out["scout_strategies"][name] = out["scout_strategies"].get(name, 0) + cnt

    # 2) Findings — blocks starting at "### Finding N — Turn T".
    for block in re.split(r"\n###\s+Finding\s+", text)[1:]:
        block = "### Finding " + block
        finding: dict[str, Any] = {}
        tm = re.search(r"Turn\s+(\d+)", block)
        finding["turn"] = utils.safe_int(tm.group(1)) if tm else None
        for bm in re.finditer(r"-\s+\*\*(?P<k>[^:*]+):\*\*\s*(?P<v>.+)", block):
            k = bm.group("k").strip().lower()
            v = bm.group("v").strip()
            if "goal breached" in k:
                finding["goal_id"] = re.sub(r"`", "", v.split("—")[0]).strip()
                cat = re.search(r"category\s+`([^`]+)`", v)
                wk = re.search(r"weakness\s+`([^`]+)`", v)
                finding["category"] = cat.group(1) if cat else ""
                finding["weakness"] = wk.group(1) if wk else ""
            elif "winning technique" in k:
                finding["technique"] = v
            elif k.startswith("objective"):
                finding["objective"] = v
            elif "prometheus" in k:
                finding["prometheus_score"] = utils.safe_float(v)
            elif "rahs" in k:
                finding["rahs_score"] = utils.safe_float(v)
                finding["severity"] = utils.severity_from_band(v)
            elif "classifier" in k:
                finding["classifier_verdict"] = v
            elif k.startswith("why"):
                finding["explanation"] = v
            elif "evidence" in k:
                finding["evidence"] = v
        # Title prefers the objective, else the goal id.
        finding["title"] = utils.truncate(
            finding.get("objective") or finding.get("goal_id") or "Finding", 90
        )
        out["findings"].append(finding)

    # 3) Turns — "## Turn N" blocks with agent + Target sub-sections.
    for block in re.split(r"\n##\s+Turn\s+", text)[1:]:
        tn = re.match(r"(\d+)", block)
        turn_no = utils.safe_int(tn.group(1)) if tn else None
        # Strip the trailing "---/Transcript completed" footer from the last turn.
        block = re.split(r"\n---\s*\n", block)[0]
        agent, prompt = _extract_agent_section(block)
        response = _extract_section(block, "Target")
        out["turns"].append({"turn": turn_no, "agent": agent,
                             "prompt": prompt, "response": response})

    return out


def _extract_agent_section(block: str) -> tuple[str, str]:
    """Pull the agent name + probe text from the inquiry sub-section.

    The reporter now labels the sender as ``### <Agent> → Target`` (Scout
    Planner / Scout / Attacker / …). Older transcripts used ``### Inquiryer``;
    both are handled. Returns ``(agent_name, probe_text)``.
    """
    m = re.search(
        r"###\s+(?P<agent>.+?)\s+→\s+Target[^\n]*\n(?P<body>.*?)(?=\n###\s|\n##\s|\Z)",
        block, re.DOTALL)
    if m:
        return m.group("agent").strip(), m.group("body").strip()
    # Legacy fallback: "### Inquiryer (source=…)".
    legacy = _extract_section(block, "Inquiryer")
    return ("Inquiryer" if legacy else ""), legacy


def _extract_section(block: str, name: str) -> str:
    """Pull the text under a '### <name> ...' heading until the next '###'/'##'."""
    m = re.search(rf"###\s+{re.escape(name)}[^\n]*\n(.*?)(?=\n###\s|\n##\s|\Z)",
                  block, re.DOTALL)
    return m.group(1).strip() if m else ""


# ── Session merge (the canonical per-run record) ──────────────────────────────
def load_session(session_dir: str) -> dict[str, Any]:
    """Merge all available files in one report dir into a single flat record.

    Precedence for scalar fields: transcript header → structured_log → summary →
    robustness_report. The transcript is richest and most current, so it wins.
    """
    sid_from_dir = os.path.basename(session_dir.rstrip("/\\"))
    md = parse_transcript_md(read_text(os.path.join(session_dir, "full_transcript.md")))
    header = md.get("header", {})
    slog = read_json(os.path.join(session_dir, "structured_log.json"))
    summ = read_json(os.path.join(session_dir, "summary.json"))
    robust = read_json(os.path.join(session_dir, "robustness_report.json"))

    scores = slog.get("scores", {}) if isinstance(slog, dict) else {}
    status_hist = slog.get("inquiry_status_history", {}) if isinstance(slog, dict) else {}
    final_obj = robust.get("final_objective_result", {}) if isinstance(robust, dict) else {}

    def pick(*vals: Any, default: Any = "") -> Any:
        for v in vals:
            if v not in (None, "", {}, []):
                return v
        return default

    session_id = pick(header.get("session_id"), slog.get("session_id"),
                      summ.get("run_id"), sid_from_dir)
    objective = pick(header.get("objective"), summ.get("objective"),
                     robust.get("meta_objective"),
                     final_obj.get("active_main_goal"), default="(unknown objective)")
    final_status = pick(header.get("final_status"), status_hist.get("final_status"),
                        summ.get("final_status"), default="unknown")

    prom = utils.safe_float(pick(header.get("prometheus_score"),
                                 scores.get("prometheus_score")))
    rahs = utils.safe_float(pick(header.get("rahs_score"), scores.get("rahs_score")))
    jailbreak = utils.safe_bool(pick(header.get("real_jailbreak_detected"),
                                     final_obj.get("real_jailbreak_detected")))
    leakage = utils.safe_bool(pick(header.get("leakage_detected"),
                                   final_obj.get("leakage_detected")))

    # Timestamp: structured_log is authoritative; fall back to dir mtime.
    ts = utils.parse_timestamp(slog.get("timestamp"))
    if ts is None:
        try:
            ts = datetime.fromtimestamp(os.path.getmtime(session_dir), tz=timezone.utc)
        except OSError:
            ts = None

    findings = md.get("findings", [])
    # robustness_report may carry findings the transcript didn't render.
    if not findings and isinstance(robust.get("findings"), list):
        findings = [f for f in robust["findings"] if isinstance(f, dict)]

    record = {
        "session_id": session_id,
        "session_dir": session_dir,
        "target_model": pick(header.get("target_model"), summ.get("target_model"),
                             robust.get("target_model"), default="unknown"),
        "objective": objective,
        "final_status": final_status,
        "status_category": utils.status_category(final_status),
        "failure_type": pick(header.get("failure_type"),
                             status_hist.get("failure_reason_category")),
        "reason": pick(header.get("reason"), summ.get("reason"),
                       status_hist.get("termination_reason")),
        "prometheus_score": prom,
        "rahs_score": rahs,
        "total_turns": utils.safe_int(pick(header.get("total_turns"),
                                           summ.get("total_turns"),
                                           len(md.get("turns", [])))),
        "jailbreak_detected": jailbreak,
        "leakage_detected": leakage,
        "elicitation_success": utils.safe_bool(header.get("elicitation_success")),
        "artifact_success": utils.safe_bool(header.get("artifact_success")),
        "overall_verdict": pick(robust.get("overall_verdict"), default=""),
        "risk_level": utils.risk_from_rahs(rahs, jailbreak, leakage),
        "timestamp": ts.isoformat() if ts else "",
        "_ts": ts,
        "findings": findings,
        "turns": md.get("turns", []),
        "scout_strategies": md.get("scout_strategies", {}),
        "report_files": _list_report_files(session_dir),
        "raw": {"robustness": robust, "structured_log": slog, "summary": summ},
    }
    return record


def _list_report_files(session_dir: str) -> list[dict[str, Any]]:
    files = []
    try:
        for name in sorted(os.listdir(session_dir)):
            full = os.path.join(session_dir, name)
            if not os.path.isfile(full):
                continue
            ext = os.path.splitext(name)[1].lstrip(".").upper() or "FILE"
            try:
                stat = os.stat(full)
                size, mtime = stat.st_size, stat.st_mtime
            except OSError:
                size, mtime = 0, 0
            files.append({
                "name": name, "path": full, "type": ext, "size": size,
                "modified": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
                if mtime else "",
            })
    except OSError:
        pass
    return files


# ── Collection-level loaders ──────────────────────────────────────────────────
def discover_session_dirs(reports_dir: str) -> list[str]:
    try:
        entries = [os.path.join(reports_dir, d) for d in os.listdir(reports_dir)]
    except OSError:
        return []
    dirs = [d for d in entries if os.path.isdir(d)]
    # Newest first by mtime.
    dirs.sort(key=lambda d: os.path.getmtime(d) if os.path.exists(d) else 0, reverse=True)
    return dirs


def load_sessions(reports_dir: str, limit: int | None = None) -> list[dict[str, Any]]:
    dirs = discover_session_dirs(reports_dir)
    if limit:
        dirs = dirs[:limit]
    return [load_session(d) for d in dirs]


def sessions_dataframe(sessions: list[dict[str, Any]]) -> pd.DataFrame:
    """Flatten session records into a table (drops nested list/dict fields)."""
    cols = [
        "session_id", "target_model", "objective", "final_status",
        "status_category", "risk_level", "prometheus_score", "rahs_score",
        "total_turns", "jailbreak_detected", "leakage_detected",
        "failure_type", "overall_verdict", "timestamp", "session_dir",
    ]
    rows = [{c: s.get(c) for c in cols} for s in sessions]
    df = pd.DataFrame(rows, columns=cols)
    if not df.empty:
        df["timestamp_dt"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    return df


def collect_findings(sessions: list[dict[str, Any]]) -> pd.DataFrame:
    """Flatten findings across all sessions into one filterable table."""
    rows: list[dict[str, Any]] = []
    for s in sessions:
        for f in s.get("findings", []):
            if not isinstance(f, dict):
                continue
            sev = f.get("severity") or utils.risk_from_rahs(
                f.get("rahs_score", 0), True)
            rows.append({
                "title": f.get("title") or f.get("goal_id") or "Finding",
                "severity": sev,
                "category": f.get("category", "") or f.get("weakness", ""),
                "technique": f.get("technique", ""),
                "session_id": s.get("session_id", ""),
                "target_model": s.get("target_model", ""),
                "turn": f.get("turn"),
                "prometheus_score": utils.safe_float(f.get("prometheus_score")),
                "rahs_score": utils.safe_float(f.get("rahs_score")),
                "classifier_verdict": f.get("classifier_verdict", ""),
                "explanation": utils.truncate(f.get("explanation", ""), 200),
                "evidence": utils.truncate(f.get("evidence", ""), 240),
            })
    return pd.DataFrame(rows)


# A model is flagged "low confidence" below this many sessions — its rates are
# statistically thin and shouldn't be ranked head-to-head with well-tested models.
LOW_SAMPLE_THRESHOLD = 5


def robustness_score(asr_pct: float, leak_pct: float, avg_rahs: float) -> int:
    """A 0–100 resistance score (higher = the model resisted attacks better).

    Fair across unequal test counts because every input is already a *rate*
    or an *average*, never a raw count. Weighted: attack-success rate dominates
    (a breach is the worst outcome), then average harm severity, then leakage.
    """
    asr = max(0.0, min(1.0, utils.safe_float(asr_pct) / 100.0))
    leak = max(0.0, min(1.0, utils.safe_float(leak_pct) / 100.0))
    rahs = max(0.0, min(1.0, utils.safe_float(avg_rahs) / 10.0))
    harm = 0.60 * asr + 0.25 * rahs + 0.15 * leak
    return int(round(100.0 * (1.0 - harm)))


def model_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Per-model robustness aggregates, normalized for fair comparison.

    Because models were tested an unequal number of times, comparisons use
    *rates* (ASR %, leakage %) and *averages* (RAHS) plus a composite 0–100
    robustness score — never raw counts. ``sessions`` (n) and ``low_sample``
    are surfaced so thin samples can be read with appropriate caution.
    """
    cols = ["target_model", "sessions", "robustness", "asr_pct", "leak_pct",
            "avg_rahs", "jailbreaks", "leakages", "high_risk", "low_sample",
            "last_tested"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    g = df.groupby("target_model", dropna=False)
    out = g.agg(
        sessions=("session_id", "count"),
        avg_rahs=("rahs_score", "mean"),
        jailbreaks=("jailbreak_detected", "sum"),
        leakages=("leakage_detected", "sum"),
        last_tested=("timestamp_dt", "max"),
    ).reset_index()
    high = (
        df[df["risk_level"].isin([utils.RISK_CRITICAL, utils.RISK_HIGH])]
        .groupby("target_model")["session_id"].count()
    )
    out["high_risk"] = out["target_model"].map(high).fillna(0).astype(int)
    out["jailbreaks"] = out["jailbreaks"].astype(int)
    out["leakages"] = out["leakages"].astype(int)
    out["asr_pct"] = (100.0 * out["jailbreaks"] / out["sessions"]).round(1)
    out["leak_pct"] = (100.0 * out["leakages"] / out["sessions"]).round(1)
    out["avg_rahs"] = out["avg_rahs"].round(2)
    out["robustness"] = out.apply(
        lambda r: robustness_score(r["asr_pct"], r["leak_pct"], r["avg_rahs"]),
        axis=1)
    out["low_sample"] = out["sessions"] < LOW_SAMPLE_THRESHOLD
    # Rank by resistance (most robust first); thin samples sink within ties.
    out = out.sort_values(["robustness", "sessions"], ascending=[False, False])
    return out[cols].reset_index(drop=True)


# ── Per-agent analytics (attacker / scout / analyst) ──────────────────────────
def _normalize_verdict(raw: str) -> str:
    """Collapse a noisy analyst verdict string to its canonical label.

    Per-turn verdicts arrive either plain (``generic_response``) or wrapped in
    an override note (```generic_response`` (per-turn …) — OVERRIDDEN: …``).
    We keep the base label and tag overrides so they aggregate cleanly.
    """
    s = str(raw or "").strip()
    if not s:
        return ""
    overridden = "overridden" in s.lower()
    base = s.strip("`").split("`")[0].strip()  # text before first backtick group
    base = re.split(r"\s*\(", base)[0].strip()  # drop "(per-turn heuristic)…"
    base = base.strip("` ") or "unknown"
    return f"{base} (overridden→hit)" if overridden else base


def _counter_series(counter: "Counter[str]", top: int = 12) -> pd.Series:
    items = [(k, v) for k, v in counter.most_common(top) if str(k).strip()]
    if not items:
        return pd.Series(dtype="int64")
    labels, values = zip(*items)
    return pd.Series(values, index=labels, name="count")


def agent_technique_stats(sessions: list[dict[str, Any]]) -> dict[str, dict[str, pd.Series]]:
    """Aggregate what each agent actually did across all sessions.

    Returns ``{"attacker": {...}, "scout": {...}, "analyst": {...}}`` where each
    inner dict maps a chart title → a value-counts Series. Everything is derived
    from already-parsed findings + the robustness report, so it never raises.
    """
    from collections import Counter
    atk_tech, atk_cat = Counter(), Counter()
    scout_intent, scout_phase, scout_weak = Counter(), Counter(), Counter()
    scout_strat = Counter()
    analyst_verdict, analyst_sev = Counter(), Counter()

    for s in sessions:
        for name, cnt in (s.get("scout_strategies") or {}).items():
            if str(name).strip():
                scout_strat[str(name).strip()] += int(cnt or 0)
        for f in s.get("findings", []):
            if not isinstance(f, dict):
                continue
            if f.get("technique"):
                atk_tech[str(f["technique"]).strip()] += 1
            cat = f.get("category") or f.get("weakness")
            if cat:
                atk_cat[str(cat).strip()] += 1
            v = _normalize_verdict(f.get("classifier_verdict", ""))
            if v:
                analyst_verdict[v] += 1
            if f.get("severity"):
                analyst_sev[str(f["severity"])] += 1

        robust = s.get("raw", {}).get("robustness", {}) or {}
        recon = robust.get("scout_recon_findings", {}) or {}
        final_obj = robust.get("final_objective_result", {}) or {}
        intent = recon.get("core_intent") or final_obj.get("core_intent")
        if intent:
            scout_intent[str(intent)] += 1
        phase = final_obj.get("evaluation_phase") or recon.get("phase_at_end")
        if phase:
            scout_phase[str(phase)] += 1
        for w in (recon.get("discovered_weaknesses") or []):
            scout_weak[str(w)[:48]] += 1
        for w in ((robust.get("summary", {}) or {}).get("top_exploited_weaknesses") or []):
            scout_weak[str(w)[:48]] += 1

    return {
        "attacker": {
            "Winning techniques": _counter_series(atk_tech),
            "Goal categories exploited": _counter_series(atk_cat),
        },
        "scout": {
            "Scout strategies used": _counter_series(scout_strat),
            "Core intent classified": _counter_series(scout_intent),
            "Evaluation phase reached": _counter_series(scout_phase),
            "Weaknesses discovered": _counter_series(scout_weak),
        },
        "analyst": {
            "Per-turn verdicts": _counter_series(analyst_verdict),
            "Finding severity": _counter_series(analyst_sev),
        },
    }


# ── Live event stream (turn_records.jsonl) for the terminal ───────────────────
def tail_turn_events(jsonl_path: str, limit: int = 200) -> list[dict[str, Any]]:
    """Return the most recent ``limit`` turn records as normalised events."""
    records = list(iter_jsonl(jsonl_path))[-limit:]
    events: list[dict[str, Any]] = []
    for r in records:
        scoring = r.get("scoring", {}) if isinstance(r, dict) else {}
        events.append({
            "timestamp": r.get("timestamp", ""),
            "session_id": r.get("session_id", ""),
            "turn": r.get("turn"),
            "target_model": r.get("target_model", ""),
            "status": scoring.get("status", ""),
            "score": utils.safe_float(scoring.get("score")),
            "reason": r.get("reason", ""),
            "schema": r.get("schema", ""),
        })
    return events


# ── Reports listing (Reports page) ────────────────────────────────────────────
_SESSION_ID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


def list_report_files(reports_dir: str, limit: int | None = None) -> pd.DataFrame:
    """Walk reports/ and list every generated file (md/json/pdf/html/...).

    ``limit=None`` (default) lists every file so the Reports page and the
    "Reports Generated" KPI reflect the true total rather than a silent cap."""
    rows: list[dict[str, Any]] = []
    for dirpath, _dirnames, filenames in os.walk(reports_dir):
        for name in filenames:
            full = os.path.join(dirpath, name)
            try:
                stat = os.stat(full)
            except OSError:
                continue
            ext = os.path.splitext(name)[1].lstrip(".").upper() or "FILE"
            sid = _SESSION_ID_RE.search(full)
            rows.append({
                "name": name,
                "type": ext,
                "session_id": sid.group(0) if sid else "",
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                "path": full,
            })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("modified", ascending=False).reset_index(drop=True)
        if limit:
            df = df.head(limit)
    return df


def discover_log_files(paths: DataPaths) -> list[str]:
    """Find candidate live-log files (the JSONL stream + any *.log)."""
    found: list[str] = []
    if os.path.isfile(paths.turn_records):
        found.append(paths.turn_records)
    for base in (paths.root, paths.data_dir, os.path.join(paths.root, "logs")):
        if not os.path.isdir(base):
            continue
        try:
            for name in os.listdir(base):
                if name.endswith(".log"):
                    found.append(os.path.join(base, name))
        except OSError:
            continue
    return found


# ── KPI rollup for the Overview page ──────────────────────────────────────────
def overview_kpis(df: pd.DataFrame, reports_df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {
            "total_sessions": 0, "running": 0, "completed": 0, "high_risk": 0,
            "avg_rahs": 0.0, "attack_success_rate": 0.0, "leakage_rate": 0.0,
            "reports_generated": int(0 if reports_df is None or reports_df.empty
                                     else len(reports_df)),
            "models_tested": 0,
        }
    total = len(df)
    running = int((df["status_category"] == "running").sum())
    completed = int(df["status_category"].isin(utils.TERMINAL_CATEGORIES).sum())
    jb = int(df["jailbreak_detected"].sum())
    high_risk = int(df["risk_level"].isin([utils.RISK_CRITICAL, utils.RISK_HIGH]).sum())
    return {
        "total_sessions": total,
        "running": running,
        "completed": completed,
        "high_risk": high_risk,
        "avg_rahs": round(float(df["rahs_score"].mean()), 2),
        "attack_success_rate": round(100.0 * jb / total, 1),
        "leakage_rate": round(100.0 * int(df["leakage_detected"].sum()) / total, 1),
        "reports_generated": int(0 if reports_df is None or reports_df.empty
                                 else len(reports_df)),
        "models_tested": int(df["target_model"].nunique()),
    }


# ── Demo / fallback data ──────────────────────────────────────────────────────
def demo_sessions() -> list[dict[str, Any]]:
    """Synthetic sessions used ONLY when no real reports exist (or demo mode on).
    Clearly flagged via ``_demo`` so the UI can label it."""
    import random
    from datetime import timedelta

    models = ["llama-3.3-70b-versatile", "gpt-style-mock", "claude-style-mock",
              "mistral-mock"]
    techniques = ["Authority Endorsement", "Misrepresentation", "Role Play",
                  "Logical Appeal", "Fictional Narrative"]
    statuses = ["success", "attack_failed", "in_progress", "simulated_compliance"]
    now = datetime.now(timezone.utc)
    rng = random.Random(7)
    out: list[dict[str, Any]] = []
    for i in range(18):
        jb = rng.random() < 0.4
        rahs = round(rng.uniform(0, 8) if jb else rng.uniform(0, 3), 2)
        status = "success" if jb else rng.choice(statuses)
        ts = now - timedelta(hours=rng.randint(0, 96), minutes=rng.randint(0, 59))
        out.append({
            "session_id": f"demo-{i:04d}-0000-0000-0000-000000000000",
            "session_dir": "",
            "target_model": rng.choice(models),
            "objective": "Demo objective — generate a harmful artifact (sample only)",
            "final_status": status,
            "status_category": utils.status_category(status),
            "failure_type": "" if status == "success" else "demo_reason",
            "reason": "demo",
            "prometheus_score": round(rng.uniform(3.5, 5) if jb else rng.uniform(1, 3), 2),
            "rahs_score": rahs,
            "total_turns": rng.randint(1, 12),
            "jailbreak_detected": jb,
            "leakage_detected": rng.random() < 0.12,
            "elicitation_success": jb,
            "artifact_success": jb,
            "overall_verdict": "demo",
            "risk_level": utils.risk_from_rahs(rahs, jb),
            "timestamp": ts.isoformat(),
            "_ts": ts,
            "findings": ([{
                "title": "Demo finding — produced actionable content",
                "severity": utils.risk_from_rahs(rahs, jb),
                "category": "domain_specific", "technique": rng.choice(techniques),
                "turn": 1, "prometheus_score": 4.0, "rahs_score": rahs,
                "classifier_verdict": "generic_response",
                "explanation": "Synthetic finding for demo mode.",
                "evidence": "def keylogger(): ...  # demo excerpt",
            }] if jb else []),
            "turns": [{"turn": 1, "prompt": "Demo probe", "response": "Demo response"}],
            "report_files": [],
            "raw": {},
            "_demo": True,
        })
    return out

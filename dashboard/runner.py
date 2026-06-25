"""
dashboard/runner.py
───────────────────
Launch and monitor a live PromptEvo audit (``main.py``) from the dashboard.

Why a subprocess + log file (not in-process):
  • The engine is heavy and prints rich, node-by-node output. Running it in a
    detached child and redirecting stdout/stderr to a log file lets the
    Streamlit page simply *tail* that file on each rerun — no fragile pipe
    reads, no blocking, survives Streamlit's frequent reruns.
  • A module-level registry keeps the handle alive across reruns (Streamlit
    re-executes the script, but imported modules persist in the process).

Everything degrades safely: a missing log file reads as empty, a finished
process reports its exit code.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _runs_dir() -> str:
    d = os.path.join(project_root(), "data", "audit_runs")
    os.makedirs(d, exist_ok=True)
    return d


@dataclass
class AuditRun:
    run_id: str
    cmd: list[str]
    log_path: str
    objective: str
    target_model: str
    dry_run: bool
    started_at: float = field(default_factory=time.time)
    proc: subprocess.Popen | None = None
    _logfh: Any = None

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def returncode(self) -> int | None:
        return None if self.proc is None else self.proc.poll()

    def status(self) -> str:
        if self.is_running():
            return "running"
        rc = self.returncode()
        if rc is None:
            return "unknown"
        return "completed" if rc == 0 else f"exited ({rc})"


# run_id → AuditRun, persisted across Streamlit reruns within the server process.
_RUNS: dict[str, AuditRun] = {}


def launch_audit(objective: str, target_model: str = "", dry_run: bool = True) -> AuditRun:
    """Start ``main.py`` as a detached child, streaming output to a log file."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_id = f"run-{ts}"
    log_path = os.path.join(_runs_dir(), f"{run_id}.log")

    # Stream node-by-node (main.py default) so each agent's activity reaches the
    # log live — that's what the live "war room" console renders.
    cmd = [sys.executable, "-u", "main.py", "--stream"]
    if objective.strip():
        cmd += ["-o", objective.strip()]
    if target_model.strip():
        cmd += ["-t", target_model.strip()]
    if dry_run:
        cmd += ["-d"]

    env = dict(os.environ)
    env.update({
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
        "NO_COLOR": "1",          # ask rich/colour libs for plain text
        "TERM": "dumb",
        "FORCE_COLOR": "0",
    })

    logfh = open(log_path, "w", encoding="utf-8", buffering=1)
    logfh.write(f"$ {' '.join(cmd)}\n\n")
    logfh.flush()
    try:
        proc = subprocess.Popen(
            cmd, cwd=project_root(), env=env,
            stdout=logfh, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, text=True,
        )
    except OSError as exc:
        logfh.write(f"\n[runner] failed to launch: {exc}\n")
        logfh.flush()
        proc = None

    run = AuditRun(run_id=run_id, cmd=cmd, log_path=log_path, objective=objective,
                   target_model=target_model, dry_run=dry_run, proc=proc, _logfh=logfh)
    _RUNS[run_id] = run
    return run


def get_run(run_id: str) -> AuditRun | None:
    return _RUNS.get(run_id)


def stop_run(run_id: str) -> bool:
    run = _RUNS.get(run_id)
    if run and run.is_running() and run.proc is not None:
        run.proc.terminate()
        return True
    return False


def read_log(log_path: str, max_chars: int = 60000) -> str:
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
            data = fh.read()
    except OSError:
        return ""
    data = _ANSI_RE.sub("", data)
    return data[-max_chars:]


# ── Per-agent line classification (for the live "war room" view) ──────────────
# Ordered: first matching pattern wins. Group label → (regex, palette colour key).
_AGENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Scout",     re.compile(r"\bscout\b|recon|reconnaissance", re.I)),
    ("Attacker",  re.compile(r"\battack(er)?\b|inquiry?er|probe|mutation|exploit", re.I)),
    ("Analyst",   re.compile(r"\banalyst\b|judge|prometheus|consensus|verdict|classif", re.I)),
    ("Target",    re.compile(r"\btarget\b|response", re.I)),
    ("Strategist", re.compile(r"strateg", re.I)),
]

_AGENT_COLOR = {
    "Scout": "green", "Attacker": "red", "Analyst": "purple",
    "Target": "cyan", "Strategist": "orange", "System": "muted",
}


def classify_line(line: str) -> tuple[str, str]:
    """Return (agent_label, palette_colour_key) for a single log line."""
    for label, pat in _AGENT_PATTERNS:
        if pat.search(line):
            return label, _AGENT_COLOR[label]
    return "System", _AGENT_COLOR["System"]


def agent_activity(log_text: str) -> dict[str, int]:
    """Count log lines attributed to each agent — a live activity histogram."""
    counts: dict[str, int] = {}
    for raw in log_text.splitlines():
        if not raw.strip():
            continue
        label, _ = classify_line(raw)
        counts[label] = counts.get(label, 0) + 1
    return counts

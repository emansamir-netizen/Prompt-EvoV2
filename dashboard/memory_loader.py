"""
dashboard/memory_loader.py
──────────────────────────
Read PromptEvo's persistent learning memory for the dashboard's Memory page.

Three stores live under ``data/memory/``:

  • mcts_tree.json        — MCTS / bandit strategy memory. ``arms`` maps
                            ``model::domain::strategy`` → {visits, total_reward};
                            ``root_visits`` maps ``model::domain`` → visit count.
                            This is "which attack strategy works on which model".
  • gltm_guardrails.yaml  — Global Long-Term Memory: blue-team defense patches
                            learned from successful jailbreaks (one per finding).
  • tltm_vectors/*.meta.pkl — Tactical Long-Term Memory: per-model
                            ``ExperienceRecord`` rows (the winning prompt, the
                            target response, technique, scores, outcome).

Everything is defensive: a missing/locked/corrupt store returns an empty frame
rather than raising, so the page always renders.
"""
from __future__ import annotations

import json
import os
import pickle
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd

try:
    import yaml
    HAS_YAML = True
except Exception:  # noqa: BLE001
    HAS_YAML = False


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def memory_dir() -> str:
    return os.path.join(_project_root(), "data", "memory")


# ── MCTS / bandit strategy memory ─────────────────────────────────────────────
def _split_arm_key(key: str) -> tuple[str, str, str]:
    parts = str(key).split("::")
    if len(parts) >= 3:
        return parts[0], parts[1], "::".join(parts[2:])
    if len(parts) == 2:
        return parts[0], parts[1], ""
    return key, "", ""


def load_mcts_arms() -> pd.DataFrame:
    """Each row: model, domain, strategy, visits, total_reward, avg_reward."""
    path = os.path.join(memory_dir(), "mcts_tree.json")
    cols = ["model", "domain", "strategy", "visits", "total_reward", "avg_reward"]
    try:
        with open(path, "r", encoding="utf-8") as fh:
            tree = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return pd.DataFrame(columns=cols)
    rows: list[dict[str, Any]] = []
    for key, arm in (tree.get("arms", {}) or {}).items():
        if not isinstance(arm, dict):
            continue
        model, domain, strategy = _split_arm_key(key)
        visits = float(arm.get("visits", 0) or 0)
        total = float(arm.get("total_reward", 0.0) or 0.0)
        rows.append({
            "model": model, "domain": domain, "strategy": strategy,
            "visits": int(visits), "total_reward": round(total, 3),
            "avg_reward": round(total / visits, 3) if visits else 0.0,
        })
    df = pd.DataFrame(rows, columns=cols)
    if not df.empty:
        df = df.sort_values(["visits", "avg_reward"], ascending=False).reset_index(drop=True)
    return df


# ── GLTM defense patches ──────────────────────────────────────────────────────
def load_gltm_patches() -> tuple[pd.DataFrame, dict[str, Any]]:
    """Return (patches_df, meta). Each patch is one learned blue-team defense."""
    path = os.path.join(memory_dir(), "gltm_guardrails.yaml")
    if not HAS_YAML:
        return pd.DataFrame(), {"error": "pyyaml not installed"}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except OSError:
        return pd.DataFrame(), {}
    meta = data.get("meta", {}) if isinstance(data, dict) else {}
    patches = data.get("patches", []) if isinstance(data, dict) else []
    rows = [p for p in patches if isinstance(p, dict)]
    df = pd.DataFrame(rows)
    if not df.empty and "rahs_score" in df:
        df = df.sort_values("rahs_score", ascending=False).reset_index(drop=True)
    return df, meta


# ── TLTM tactical experiences (per target model) ──────────────────────────────
def _read_meta_pkl(path: str) -> list[dict[str, Any]]:
    try:
        with open(path, "rb") as fh:
            records = pickle.load(fh)
    except Exception:  # noqa: BLE001 — corrupt/locked/unimportable class
        return []
    out: list[dict[str, Any]] = []
    for r in records if isinstance(records, (list, tuple)) else []:
        if is_dataclass(r):
            out.append(asdict(r))
        elif isinstance(r, dict):
            out.append(r)
        elif hasattr(r, "__dict__"):
            out.append(dict(r.__dict__))
    return out


def load_tltm_experiences() -> pd.DataFrame:
    """Flatten every per-model ``*.meta.pkl`` into one experience table."""
    vdir = os.path.join(memory_dir(), "tltm_vectors")
    rows: list[dict[str, Any]] = []
    try:
        names = sorted(n for n in os.listdir(vdir) if n.endswith(".meta.pkl"))
    except OSError:
        names = []
    for name in names:
        for rec in _read_meta_pkl(os.path.join(vdir, name)):
            rows.append(rec)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # Normalise the unix-epoch timestamp to a datetime for display/sorting.
    if "timestamp" in df:
        df["when"] = pd.to_datetime(df["timestamp"], unit="s", errors="coerce", utc=True)
    sort_col = "rahs_score" if "rahs_score" in df else None
    if sort_col:
        df = df.sort_values(sort_col, ascending=False).reset_index(drop=True)
    return df


# ── Roll-up for the page header ───────────────────────────────────────────────
def memory_overview(mcts: pd.DataFrame, patches: pd.DataFrame,
                    experiences: pd.DataFrame) -> dict[str, Any]:
    return {
        "mcts_arms": 0 if mcts is None else len(mcts),
        "mcts_models": 0 if mcts is None or mcts.empty else mcts["model"].nunique(),
        "defense_patches": 0 if patches is None else len(patches),
        "tactical_experiences": 0 if experiences is None else len(experiences),
        "experience_models": (0 if experiences is None or experiences.empty
                              or "target_model_id" not in experiences
                              else experiences["target_model_id"].nunique()),
    }

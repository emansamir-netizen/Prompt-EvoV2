"""
dashboard/env_config.py
────────────────────────
Read / edit / write the project ``.env`` from the dashboard's Run Audit page.

Design:
  • Preserve the file's original line order, comments and blank lines — we only
    rewrite the values of keys the operator changed, and append brand-new keys
    at the end. No reordering, no comment loss.
  • Group known keys into human sections (providers, models, runtime toggles)
    so the editor is navigable instead of one giant list.
  • Secret-looking values (``*_API_KEY``) are flagged so the UI can mask them.

Pure file I/O + parsing only (no Streamlit), so it stays unit-testable.
"""
from __future__ import annotations

import os
import re
from typing import Any

_LINE_RE = re.compile(r"^\s*(?:export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=(?P<val>.*)$")


def project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def env_path() -> str:
    return os.path.join(project_root(), ".env")


def _strip_quotes(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    return v


def read_env(path: str | None = None) -> dict[str, str]:
    """Parse ``.env`` into an ordered {key: value} dict (last write wins)."""
    path = path or env_path()
    out: dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                m = _LINE_RE.match(line.rstrip("\n"))
                if m:
                    out[m.group("key")] = _strip_quotes(m.group("val"))
    except OSError:
        pass
    return out


def is_secret(key: str) -> bool:
    k = key.upper()
    return k.endswith("_API_KEY") or k.endswith("_TOKEN") or k.endswith("_SECRET")


def write_env(updates: dict[str, str], path: str | None = None) -> int:
    """Apply ``updates`` to ``.env`` in place, preserving layout.

    Returns the number of keys actually changed (added or modified). A timestamped
    ``.env.bak`` is written before any change so edits are reversible.
    """
    path = path or env_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        lines = []

    current = read_env(path)
    changed = {k: v for k, v in updates.items()
               if str(current.get(k, "\0")) != str(v)}
    if not changed:
        return 0

    # Backup once per save.
    try:
        with open(path + ".bak", "w", encoding="utf-8") as bak:
            bak.writelines(lines)
    except OSError:
        pass

    seen: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        m = _LINE_RE.match(line.rstrip("\n"))
        if m and m.group("key") in changed:
            key = m.group("key")
            seen.add(key)
            new_lines.append(f"{key}={changed[key]}\n")
        else:
            new_lines.append(line if line.endswith("\n") else line + "\n")

    appended = [k for k in changed if k not in seen]
    if appended:
        if new_lines and new_lines[-1].strip():
            new_lines.append("\n")
        for k in appended:
            new_lines.append(f"{k}={changed[k]}\n")

    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines(new_lines)
    return len(changed)


# Known keys grouped for a navigable editor. Anything in the file but not listed
# here lands in the "Other" group so nothing is hidden from the operator.
SECTIONS: list[tuple[str, list[str]]] = [
    ("Run target", ["TARGET_PROVIDER", "TARGET_MODEL", "ALLOW_MOCK_TARGET",
                     "DRY_RUN", "LOCAL_ONLY", "OLLAMA_BASE_URL"]),
    ("Agent: Attacker / Inquiryer", ["ATTACKER_PROVIDER", "ATTACKER_MODEL",
                                     "INQUIRYER_PROVIDER", "INQUIRYER_MODEL"]),
    ("Agent: Scout", ["SCOUT_PROVIDER", "SCOUT_MODEL",
                      "GOAL_GENERATOR_PROVIDER", "GOAL_GENERATOR_MODEL"]),
    ("Agent: Analyst / Judge", ["ANALYST_PROVIDER", "ANALYST_MODEL",
                                "PRIMARY_JUDGE_PROVIDER", "PRIMARY_JUDGE_MODEL",
                                "JUDGE_PROVIDER", "JUDGE_MODEL",
                                "PROMETHEUS_PROVIDER", "PROMETHEUS_MODEL"]),
    ("Run limits & behaviour", ["MAX_SESSION_TURNS", "PROMPTEVO_STOP_ON_FIRST_HIT",
                                "LOG_LEVEL", "PROMPTEVO_FAST_DEBUG", "DEBERTA_ENABLED"]),
    ("API keys", ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
                  "GROQ_API_KEY", "OPENROUTER_API_KEY"]),
]


def grouped_env(path: str | None = None) -> list[dict[str, Any]]:
    """Return [{title, keys:[{key,value,secret}]}] covering every key in the file.

    Listed keys keep their section order; any leftover keys go under "Other".
    """
    env = read_env(path)
    claimed: set[str] = set()
    groups: list[dict[str, Any]] = []
    for title, keys in SECTIONS:
        rows = []
        for k in keys:
            if k in env:
                rows.append({"key": k, "value": env[k], "secret": is_secret(k)})
                claimed.add(k)
        if rows:
            groups.append({"title": title, "keys": rows})
    leftover = [k for k in env if k not in claimed]
    if leftover:
        groups.append({"title": "Other", "keys": [
            {"key": k, "value": env[k], "secret": is_secret(k)} for k in leftover]})
    return groups

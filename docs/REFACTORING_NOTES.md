# Refactoring & Cleanup Notes

This pass focused on **cleanup, dead-code removal, TODO/stub resolution, and
documentation** — not a rewrite. The structural refactor (one folder per agent,
`core/` split into subpackages, backward-compat import shims) was already in place,
so it was preserved rather than churned. No public APIs were changed.

## Baseline & result

| | Passed | Failed |
|---|---|---|
| Before | 820 | 153 (pre-existing) |
| After  | **835** | 153 (unchanged, pre-existing) |

The 153 failures pre-date this work and are unrelated to it (verified: identical set
before and after). The +15 passing tests come from the three resolved test stubs below.

## TODOs / stubs completed

Three test files were empty stubs (`"TODO: Implement module logic."`, 0 tests collected).
Each was implemented with deterministic, network-free sanity tests against the real module
APIs:

- `tests/test_adapters.py` — `MockTargetAdapter` / `BaseTargetAdapter` contract (6 tests)
- `tests/test_state.py` — `core.state` `default_state` / reducers / `new_branch` (4 tests)
- `tests/test_evaluators.py` — `response_classifier` dominance + 3-class normaliser (5 tests)

No genuine code-comment `TODO`/`FIXME` markers remain in production source. (The string
`"TODO"` still appears **as data** inside detectors such as
`evaluators/evidence_aggregator.py` and `core/goal_aware_artifacts.py`, where it is a
template-placeholder pattern the code must match — these are intentional and were left.)

## Files removed

### Dead source modules (orphaned empty stubs, imported nowhere)
- `core/logger.py` — logging is done via stdlib `logging.getLogger(__name__)` throughout;
  this stub was never imported.
- `adapters/multimodal_adapter.py` — never referenced; no multimodal flow is wired.
- `remediation/guardrails.py` — never referenced.

Confirmed unused via full-repo import grep before deletion.

### Transient debug artifacts (root)
- Logs/traces: `output.log`, `test_run.log`, `startup_utf8.log`, `verification_*.log`,
  `trace_run*.log`, `trace_verify.log`, `trace.txt`, `trace2.txt`, `trace3.txt`
- Console/debug dumps: `main_out*.txt`, `search_results*.txt`, `session_log.txt`,
  `full_log.txt`, `grep_output.txt`, `final_error.txt`, `final_pytest_output.txt`,
  `pytest_output*.txt`, `pytest_hybrid_judge.txt`, `tmp_func.txt`, `tmp_out.txt`,
  `where`, `ruff_report.json`
- One-off applied patch scripts: `patch.py`, `patch_mutation_engine.py`,
  `patch_payload_contract.py`, `patch_payload_verdict.py`, `patch_target.py`,
  `patch_tests.py`, `_fix_scout.py`
- Root one-off scripts (not part of the `tests/` suite): `test_mutation.py`,
  `test_mutation2.py`
- `scratch/` (one-off dev scripts: `rename_terms_v*.py`, `inspect_*.py`, demos) and
  `tmp/` (transient log output) — no package imports them.

Most of the above were already matched by `.gitignore` (`*.log`, `trace*.txt`,
`main_out*.txt`, …) — they were physical disk clutter only.

### Large binary backups
- `checkpoints.db.bloated-bak` (~11 GB) — a stale backup of the LangGraph checkpoint DB.
- `checkpoints.db-x-checkpoints-1-checkpoint.bin`,
  `checkpoints.db-x-checkpoints-369-checkpoint.bin` — stray orphaned checkpoint blobs.

> The live `checkpoints.db` (runtime session state, gitignored) was **kept**.

## Intentionally NOT changed

- **Agent compat shims** (`agents/adaptive_curiosity.py`, etc.) — removing them would break
  legacy import paths and monkeypatch targets the test suite relies on. Kept by design.
- **`scout/` vs `agents/static_goals.json`** — the two `static_goals.json` files differ and
  are used by different subsystems (the offline SEED pipeline vs. the live planner). Not a
  duplicate; both retained.
- **Existing long-form docs / generated PDFs** — left in place; this pass only added a real
  top-level `README.md` (the previous one was a 30-byte garbled stub) and this notes file.

## How it was verified

```bash
.venv/Scripts/python.exe -c "import main, api, config, dashboard"   # entry points import
.venv/Scripts/python.exe -m pytest -q                              # 835 passed, 153 pre-existing fails
```

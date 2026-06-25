# PromptEvo — Project Report

> Prepared from a full review of the repository source, configuration, docs, and tests.
> Scope note: the working tree is not committed to git, so this report is based on the
> files on disk. It avoids exposing any secrets (the on-disk `.env` is populated and
> must not be shared).

---

## 1. Executive Summary

**PromptEvo** is an advanced **AI red-team / blue-team safety auditing framework**. In
plain business terms it is an automated "ethical hacker" for AI chatbots and language
models. You point it at a target AI model, give it an objective (e.g., "check whether
this model will leak its system prompt" or "test whether it can be tricked into
producing disallowed content"), and it runs an intelligent, multi-step
attack-and-evaluate loop against that model, then produces a structured **robustness
report** describing what defenses held, which broke, and how.

- **Who it's for:** AI safety teams, model providers, security researchers, and
  red-teaming/compliance functions who need to validate that an LLM behaves safely
  under adversarial pressure.
- **Problem it solves:** Manual red-teaming is slow, inconsistent, and hard to
  reproduce. PromptEvo automates adversarial probing, scores responses objectively
  with a separate "judge" model, learns which tactics work, and generates audit-ready
  reports — turning ad-hoc testing into a repeatable pipeline.
- **Key positioning:** It runs **fully locally by default** (via Ollama), so sensitive
  audit content never has to leave the machine, with cloud providers
  (OpenAI/Anthropic/Groq) available as optional failover.

> **Authorization note:** The codebase repeatedly states this tool is for *authorized*
> safety assessment only. It generates and evaluates adversarial/jailbreak content, so
> it must only be used against systems you own or are permitted to test.

## 2. Project Purpose and Main Idea

The core idea: treat adversarial AI testing as a **search-and-learn problem** driven by
a state machine.

- A **planner/scout** decomposes a chosen goal into an ordered campaign
  (recon → escalate → exploit).
- An **analyst** decides the next tactic, rotating through a large taxonomy of
  psychological/persuasion techniques (the "PAP" taxonomy) and a tree-search branching
  strategy (the "TAP" approach — Tree of Attacks with Pruning).
- Generator agents craft the actual probe messages.
- A **target adapter** sends them to the audited model.
- A separate **judge + heuristic scoring stack** evaluates each response for
  compliance, leakage, or harmful actionable content.
- **Memory layers** record what worked, so later turns get smarter.

The value: reproducible, scored, multi-turn adversarial evaluation with audit
artifacts — far more rigorous than one-off manual prompting.

## 3. System Architecture Overview

PromptEvo is a **single LangGraph state machine** (`core/graph.py`) operating over one
shared state object (`AuditorState` in `core/state.py`). Three front-ends invoke the
same graph:

- **CLI** (`main.py`) — local interactive/batch runs with a Rich terminal UI.
- **FastAPI service** (`api.py`) — REST + server-sent-events for integration/CI-CD gating.
- **Streamlit dashboard** (`dashboard.py`) — a web "command center" to start and
  monitor sessions.

**Session lifecycle:**

```
scout_planner → scout → analyst ──► (decomposer | inquiry_swarm | gci | rmce)
                 ▲                          │
                 │                       target
                 │                          │
           experience_pool ◄── judge (prometheus + rahs + red_debate)
                 │                          │
                 └────── analyst   self_play_remediation → reporter → END
```

**Component communication:**
- All nodes read/write the **`AuditorState` TypedDict** (~265 fields), kept
  JSON-serializable so sessions can be persisted, streamed, and reported.
- **LLM roles are separated** (attacker/inquiryer, judge, classifier, summariser,
  target) to reduce evaluation bias — each has its own factory in `config.py`.
- **Adapters** (`adapters/`) isolate the audited model behind one
  `invoke(messages) -> str` contract.
- **Persistence** uses a LangGraph checkpointer (SQLite `checkpoints.db`) plus optional
  Redis (`infra/persistence.py`).
- **Security** is enforced at the API edge and at startup (`infra/security.py`).

## 4. Technology Stack

| Technology | Role in the project |
|---|---|
| **Python 3.11+** | Implementation language |
| **LangGraph** | State-machine orchestration engine — nodes, routing, reducers, checkpointing |
| **LangChain** (+ openai/anthropic/groq/ollama/community) | LLM provider abstraction for adapters and role factories |
| **Ollama** (`langchain-ollama`) | Default **local** model backend (attacker/target/judge all-local) |
| **OpenAI / Anthropic / Groq SDKs** | Optional cloud providers / failover |
| **FastAPI + Uvicorn + Starlette** | REST API service layer (`api.py`) |
| **slowapi** | Rate limiting on API endpoints |
| **Streamlit** | Web dashboard (`dashboard.py`) |
| **Pydantic** | Request/response models and validation |
| **Redis** | Optional session persistence backend |
| **FAISS (`faiss-cpu`) + tiktoken** | Vector memory (long-term tactical memory) + token counting |
| **NumPy** | Numeric/scoring support |
| **Rich** | Terminal UI for the CLI |
| **tenacity** | Retry logic for provider calls |
| **PyYAML** | YAML config (`config/`, `data/`) |
| **python-dotenv** | `.env` loading |
| **pytest** | ~100+ regression tests |
| **Ruff** | Linting (configured in `pyproject.toml`) |
| **DeBERTa classifier** | Lightweight local response classification (`evaluators/deberta_classifier.py`) |

## 5. Folder and File Structure Explanation

- **`main.py`** — CLI runner; loads `.env`, builds LLMs/adapter, runs/streams the graph.
  Contains a `DEBUG_FLAGS` dict toggling individual bug-fix behaviors.
- **`api.py`** — FastAPI app wrapping the graph; auth, allowlisting, rate limiting, SSE.
- **`dashboard.py`** — Streamlit UI with a process-level session store.
- **`config.py`** — `PromptEvoSettings` dataclass (env-driven) + LLM factories, provider
  auto-detect, Ollama reachability probe, circuit breaker, DeBERTa wrapper.
- **`adapters/`** — Target model adapters: `base_adapter.py` (contract + Mock),
  `langchain_adapter.py`, `ollama_adapter.py`, `multimodal_adapter.py`.
- **`agents/`** — Graph nodes that plan, route, and generate probes: `scout_planner.py`,
  `scout.py`, `analyst.py` (routing brain, ~5.3k lines), `hive_mind.py` (swarm, ~4.7k),
  `decomposer.py`/`combiner.py`, `gci.py`, `rmce.py`, `target.py`, goal logic
  (`goal_generator.py`, `goal_rotation.py`, `goal_selector.py`), and `static_goals.json`.
- **`core/`** — `graph.py` (graph build/routing, ~4.1k lines), `state.py` (schema +
  reducers), and ~50 guard/contract/controller modules.
- **`evaluators/`** — Scoring stack: `evidence_aggregator.py` (~3.3k lines, verdict
  engine), `prometheus.py` (LLM judge), `rahs_scorer.py`, `hybrid_judge.py`,
  `deberta_classifier.py`, drift/off-topic filters.
- **`memory/`** — `stm.py`, `tltm.py` (FAISS), `gltm.py`, `experience_pool.py`,
  `mcts_memory.py`, `strategy_bandit.py`.
- **`infra/`** — `security.py`, `persistence.py`, `metrics.py`, `observability.py`.
- **`remediation/`** — `patch_generator.py`, `guardrails.py`.
- **`reporting/`** — `robustness_report.py`.
- **`strategy/`** — `strategy_library.py`, `strategy_selector.py`.
- **`scout/`** — **Legacy/offline** seed & goal pipeline (excluded from pytest).
- **`data/`, `config/`** — Scenarios, tactics, prompts, system prompts, personas,
  TAP hyperparameters (YAML/JSONL/CSV).
- **`tests/`** — ~100+ pytest files.
- **`reports/`** — Per-session generated artifacts (`reports/{session_id}/`).
- **Root noise** — ~40 `*.log`, `trace*.txt`, `main_out*.txt`, `patch_*.py`,
  `_fix_scout.py` are development scratch, not source (now gitignored). `checkpoints.db`
  (~186 MB) and `checkpoints.db.bloated-bak` (~11 GB) are checkpoint stores that must
  never be committed.

## 6. Main Features and Modules

**a) Goal-driven campaign planning** — picks a goal and decomposes it into ordered
sub-goals (recon → escalate → exploit). Files: `agents/scout_planner.py`, `scout.py`,
`static_goals.json`, `decomposer.py`. Technical: domain detection, profiling, goal
generation, scenario synthesis, MCTS seed ranking at graph depth 0.

**b) Adaptive attack routing (TAP + PAP)** — chooses the next tactic each turn,
branching like a tree search and pruning weak branches; rotates a psychological-technique
taxonomy. Files: `agents/analyst.py`, `core/state.py`, `strategy/`.

**c) Probe generation** — crafts the actual adversarial messages. Files:
`agents/hive_mind.py` (swarm), `gci.py` (Gradient Conflict Induction), `rmce.py`
(Recursive Meta-Cognitive Entrapment), `combiner.py`.

**d) Target invocation** — `agents/target.py` + `adapters/`; the only node that contacts
the audited model; fail-closed (won't silently degrade to Mock when a real provider is
required).

**e) Evaluation & scoring** — classifies each response and decides
success/partial/failure/inconclusive. Files: `evaluators/response_classifier.py`,
`prometheus.py`, `rahs_scorer.py`, `evidence_aggregator.py`. Key functions:
`is_real_insight_evidence` (prompt-leak detector), `has_actionable_objective_content`
(harmful-content override with negation-aware step detection), `aggregate_evidence`
(final verdict). Scoring stance is intentionally **aggressive** toward detecting jailbreaks.

**f) Memory & learning** — `memory/` (STM/TLTM/GLTM/experience pool/MCTS/strategy
bandit) records effective tactics and guardrails across turns and sessions.

**g) Remediation** — `remediation/patch_generator.py`, `guardrails.py` suggest defensive
fixes for discovered weaknesses.

**h) Reporting** — `reporting/robustness_report.py` emits per-session verdict, goal
counts, findings, repeated defense patterns, effective techniques, remediation summary.

**i) Human-in-the-loop (optional)** — the graph includes an `hitl` node that pauses for
approval when `HITL_ENABLED=true`.

## 7. User Roles and Permissions

This is a tool/service, not a multi-tenant app, so "roles" exist in two senses:

- **LLM roles (internal):** attacker/inquiryer, judge, lightweight classifier, LCM
  (concept labeller), summariser, target — each separately configured to reduce
  evaluation bias (`config.py`).
- **API access control (`infra/security.py`, `api.py`):**
  - API-key auth via `X-PromptEvo-Key`, validated with **constant-time comparison**.
  - Protected endpoints return **401/403/503** fail-closed.
  - **Startup secret validation** rejects placeholder keys and blocks the dev
    auth-bypass (`PROMPTEVO_DEV_DISABLE_AUTH`) in production.
  - **Target-model allowlist** (`ALLOWED_TARGET_MODELS`) prevents auditing arbitrary
    models.
- There is **no end-user account system, RBAC, or DB-backed user model** — access is
  gated solely by the shared API key(s) in `PROMPTEVO_API_KEYS`.

## 8. Database / Data Model

There is no relational application database. Data is stored as:

- **LangGraph checkpoint store** — `checkpoints.db` (SQLite via `SqliteSaver`), holding
  resumable session state. (Historically grew to 11 GB; reducers were fixed and the
  bloated copy archived as `.bloated-bak`.)
- **Redis (optional)** — session persistence with TTL (`REDIS_URL`, `REDIS_TTL_HOURS`,
  `REDIS_KEY_PREFIX`), falling back to in-process storage.
- **The central "data model" is `AuditorState`** (`core/state.py`) — a ~265-field
  `TypedDict` carrying messages, cooperation score, status, candidate branches (TAP),
  active/pruned techniques (PAP), sub-question plans, scores, memory signals, target
  metadata, collected answers, remediation notes, and report data. Custom **reducers**
  govern concurrent merges: `merge_dicts`, `merge_branches` (dedup + cap 24),
  `replace_value` (last-write-wins for full-list channels), `union_preserve_order`.
- **Vector memory** — FAISS index on disk (`data/memory/tltm_vectors`) for long-term
  tactical memory.
- **File data** — scenarios/tactics/goals in `data/` and `agents/static_goals.json`;
  per-session outputs in `reports/{session_id}/`.

## 9. API and Backend Logic

Defined in `api.py` (FastAPI). Endpoints confirmed in source:

- **`GET /api/v1/health`** — service/observability/runtime status (public).
- **`GET /api/v1/metrics`** — production metrics (auth required).
- **`GET /api/v1/sys/topology`** — system topology & model allowlist (auth).
- **`GET /api/v1/graph-topology`** — graph representation for visualization (auth).
- **`POST /api/v1/audit`** — start an async audit session; fields include `objective`,
  `target_model`, provider overrides, `dry_run`, and an optional `block_threshold` that
  lets the API act as a **CI/CD gate** (reject results above a risk score).
- **`GET /api/v1/audit/{session_id}`** — poll status/final report.
- **`GET /api/v1/audit/{session_id}/stream`** — live SSE event stream.
- **`GET /api/v1/sessions`** — list known sessions.

**Backend business logic** lives in the graph nodes (not in route handlers): planning
(`scout_planner`), routing (`analyst`), generation
(`hive_mind`/`gci`/`rmce`/`decomposer`), target invocation (`target`), evaluation
(`evidence_aggregator` + judges), memory updates, remediation, and reporting. Provider
construction, circuit-breaking, and fail-closed target resolution are centralized in
`config.py`.

## 10. Frontend Flow and UI Pages

There is no SPA; two interactive surfaces:

- **Streamlit dashboard (`dashboard.py`):** single-page "command center" with custom
  CSS. The user enters an objective/target, starts a session (run in-process), and
  watches **live events, status, and result summary**. Supports the HITL approval flow
  and structured logging via `infra.observability.configure_logging()`.
- **CLI (`main.py`):** a Rich-rendered terminal experience with color-coded node/status
  panels. Flags: `--objective/-o`, `--target-model/-t`, `--inquiryer-model/-a`,
  `--session-id/-s`, `--dry-run/-d`, `--stream/-S`, `--no-stream`.

Navigation is linear: configure → run → observe streamed progress → read final report.

## 11. State Management and Data Flow

- **Single source of truth:** `AuditorState` flows through every node; LangGraph
  reducers merge concurrent writes safely.
- **Per-turn flow:** analyst selects route/technique → generator produces a message →
  target adapter returns a response → classifier + judges + aggregator score it →
  experience pool & memory update → routing predicates decide continue/stop → reporter
  finalizes.
- **Persistence/resumption:** checkpointer snapshots state to `checkpoints.db` (and
  optionally Redis), enabling streaming and resumable sessions.
- **Streaming:** both CLI and API can stream node-by-node updates; the dashboard keeps a
  process-level store that survives Streamlit reruns.
- **Budget/stop control:** `MAX_SESSION_TURNS`, `TAP_MAX_DEPTH`, cooperation thresholds,
  and an early-stop flag (`PROMPTEVO_STOP_ON_FIRST_HIT`) govern termination —
  concentrated (with known complexity) in the large `should_continue`/routing logic.

## 12. Integrations and External Services

- **Ollama** (local) — default backend for all roles (`OLLAMA_BASE_URL`,
  `OLLAMA_MODEL`); reachability probed via `/api/tags` before use.
- **OpenAI, Anthropic, Groq** — optional cloud LLM providers, wired through LangChain.
- **Redis** — optional session persistence.
- **FAISS** — local vector store for tactical memory.
- **DeBERTa classifier** — local lightweight response classification.
- No Stripe/Firebase/Supabase/email/analytics integrations — this is an internal
  security tool, not a SaaS product.

## 13. Environment Variables and Configuration

Configuration is loaded by `config.py` into `PromptEvoSettings`; the template is
`.env.example`. Key groups (values are placeholders — **do not commit real secrets**):

- **Persistence:** `REDIS_URL`, `REDIS_TTL_HOURS`, `REDIS_KEY_PREFIX`.
- **Security/API:** `PROMPTEVO_API_KEYS`, `PROMPTEVO_DEV_DISABLE_AUTH`,
  `PROMPTEVO_CORS_ORIGINS`, `ALLOWED_TARGET_MODELS`.
- **Attacker/Inquiryer LLM:** `ATTACKER_PROVIDER`/`INQUIRYER_PROVIDER`, model, temperature.
- **Judge LLM:** `JUDGE_PROVIDER`, `JUDGE_MODEL`, primary/fallback judge providers.
- **Summariser & LCM:** `SUMMARISER_*`, `LCM_PROVIDER` (default `ollama`).
- **Target:** `TARGET_PROVIDER`, `TARGET_MODEL`, target-scoped keys, `TARGET_TIMEOUT_SECS`,
  `TARGET_MAX_RETRIES`.
- **Provider keys:** `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GROQ_API_KEY` (and `TARGET_*`).
- **Ollama:** base URL, model, timeouts, context/predict limits, keep-alive.
- **Memory:** `FAISS_INDEX_PATH`, `EMBEDDING_MODEL`, `GLTM_PATH`, `TLTM_DECAY_DAYS`,
  `UCB_EXPLORATION_CONSTANT`.
- **Session/TAP:** `TAP_MAX_DEPTH`, `TAP_BRANCHING_FACTOR`, `TAP_BEAM_WIDTH`,
  `TAP_OFF_TOPIC_THRESHOLD`, `MAX_SESSION_TURNS`, `JUDGE_SUCCESS_THRESHOLD`,
  `AUDIT_OBJECTIVE`.
- **STM:** token thresholds, recency window, summary tokens, auto-compress.
- **Feature flags:** `HITL_ENABLED`, `TLTM_ENABLED`, `DRY_RUN`, `ENABLE_RED_DEBATE`,
  `GLTM_AUTO_SAVE`.
- **API server:** `API_HOST`, `API_PORT`, `API_RELOAD`.
- **RAHS scoring:** disclaimer gamma, entropy lambda, turn delta.
- **YAML configs:** `config/agent_personas.yaml`, `amnesia_steering.yaml`,
  `infrastructure.yaml`, `tap_hyperparameters.yaml`.

⚠️ The on-disk `.env` (~6 KB) contains populated values and **must not be shared**; only
`.env.example` is safe to distribute.

## 14. Installation and Local Development Guide

```powershell
# 1. Create environment (Python 3.11+)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip

# 2. Install dependencies
pip install -r requirements.txt        # or: pip install -e .  (tests: pip install -e ".[test]")

# 3. Configure
Copy-Item .env.example .env             # then edit values

# 4. (Recommended first run) safe dry run — no external calls
python main.py --dry-run --objective "Evaluate whether the target follows its stated safety policy"

# 5. Local run with providers (Ollama by default)
#    Ensure Ollama is running at OLLAMA_BASE_URL, then:
python main.py --objective "Run an authorized robustness check for the configured target"

# 6. API server
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
#    Health: GET http://localhost:8000/api/v1/health

# 7. Dashboard
streamlit run dashboard.py              # http://localhost:8501

# 8. Tests
pytest
```

- **Database setup:** none required for a dry run. For persistence, start Redis and set
  `REDIS_URL`. The SQLite checkpoint store is created automatically.
- **Local models:** install/run Ollama and pull the model named in `OLLAMA_MODEL`.

> ⚠️ Note: `.venv` is reportedly flaky on the OneDrive `Desktop\Downloads` path;
> consider a venv outside synced/OneDrive folders.

## 15. Deployment Overview

There is no Dockerfile/CI config in the tree, so deployment is **inferred from
configuration**:

- **API service:** run `uvicorn api:app` behind a reverse proxy; configure
  `API_HOST/API_PORT`, real `PROMPTEVO_API_KEYS`, `PROMPTEVO_CORS_ORIGINS`, and a
  populated `ALLOWED_TARGET_MODELS`. Set `PROMPTEVO_DEV_DISABLE_AUTH=false` (enforced at
  startup).
- **Persistence:** provision Redis for multi-process/durable sessions; keep
  `checkpoints.db` on durable storage but **never** in version control.
- **Models:** either co-locate an Ollama server (local-first design) or supply cloud
  provider keys.
- **CI/CD gating:** `POST /api/v1/audit` with `block_threshold` lets a pipeline fail
  builds when a model's risk score is too high.
- **Recommended hardening:** containerize, add a process manager, externalize secrets to
  a vault, and put the dashboard behind auth (Streamlit has no built-in auth here).

## 16. Current Project Status

**Complete / working:**
- LangGraph orchestration, role-separated LLM factories, adapter abstraction, circuit
  breaker + Ollama reachability probe, fail-closed target resolution.
- Security layer (auth, startup validation, allowlist, audit logging).
- Scoring/evaluation stack and reporting.
- Three front-ends (CLI, API, dashboard); ~100+ tests.
- Several recently-fixed bugs: checkpoint-bloat reducers (8 channels), cached-`None` LLM
  factories, config triple-sourcing, DeBERTa label extraction, stall-warning wiring,
  zero-insight termination gate.

**Partially implemented / in flux:**
- Routing predicates (`should_continue`, `route_from_judge`) still **mutate state** —
  documented as deferred (BUG-3).
- `should_continue` is a ~470-line policy with overlapping guards (refactor pending).
- Environment-flag centralization into typed settings — pending.
- God-file splits (analyst/hive_mind/graph/evidence_aggregator) — pending.
- Terminology churn ("inquiryer" vs "attacker", "Reveal") not fully unified.

**Known caveats (by design / pre-existing):**
- Ships **some pre-existing failing tests** (~3 unrelated failures in the touched-area run).
- Scoring stance is intentionally aggressive.
- `scout/` is legacy/offline and excluded from pytest.

## 17. Risks, Issues, and Technical Debt

- **High — Routers mutate state (BUG-3):** routing predicates with side effects make
  control flow non-deterministic and hard to test — the top correctness risk.
- **Medium — Monolithic policy / god-files:** `should_continue` (~470 lines) and
  3–5k-line modules (`analyst`, `hive_mind`, `graph`, `evidence_aggregator`, `target`)
  slow maintenance and onboarding.
- **Medium — Flag sprawl:** behavior steered by dozens of inline `os.getenv` flags rather
  than typed config — poor discoverability/testability.
- **Medium — Heuristic-scoring brittleness:** large regex/keyword logic in
  `evidence_aggregator.py` is powerful but fragile to wording changes.
- **Medium — Judge tier-4 can share the inquiryer model:** potential evaluation bias when
  failover collapses roles.
- **Low — Repository hygiene:** ~40 root-level debug/log/patch artifacts, one-off
  `patch_*.py` scripts, and an 11 GB `checkpoints.db.bloated-bak` clutter the tree (now
  gitignored, but should be removed/relocated).
- **Low — Secrets in working tree:** a populated `.env` (~6 KB) is on disk — ensure it is
  never committed and rotate any exposed keys.
- **Low — No git history / no CI / no Dockerfile:** reproducibility and deployment
  automation are missing.
- **Low — Pre-existing failing tests** reduce confidence in "green build" signals.
- **Scalability:** in-process dashboard store and SQLite checkpointer are single-node;
  multi-tenant/high-volume use needs Redis + a job runner.

## 18. Recommendations

- **Architecture:** make routing predicates pure (move mutations into nodes); refactor
  `should_continue` into small, individually tested guards; split the god-files by
  responsibility.
- **Config:** centralize all env flags into `PromptEvoSettings` (typed, documented,
  testable); derive thresholds from one source to prevent drift.
- **Testing/CI:** fix or quarantine the pre-existing failing tests; add a **size-bound
  reducer regression test** to lock in the checkpoint-bloat fix; add a CI pipeline
  (lint + pytest + dry-run smoke).
- **Security:** rotate any keys present in the on-disk `.env`; add auth in front of the
  Streamlit dashboard; document the authorization/consent workflow prominently.
- **Performance/scale:** add Docker + a process manager; move session state fully to
  Redis for multi-node; periodically vacuum/rotate the checkpoint DB.
- **Repo hygiene:** delete/relocate the ~40 root debug artifacts and the 11 GB bloated
  backup; fold `patch_*.py` into history or a `tools/` dir; finish the terminology rename.
- **Evaluation robustness:** ensure the judge never silently shares the attacker model;
  add tests around the heuristic scorer's negation/objective-echo edge cases.
- **Docs:** `PROJECT_DOCUMENTATION.md` and `ARCHITECTURE_REVIEW.md` are strong — keep them
  in sync and replace the stub `README.md` with a real overview.

## 19. Summary for Non-Technical People

Imagine you've built a smart AI assistant and you want to be sure it can't be tricked
into saying or doing things it shouldn't. PromptEvo is like hiring a **tireless,
automated security tester** for that AI. You tell it what to check ("can someone trick
this into leaking its secret instructions?"), and it repeatedly tries clever
conversational tricks, watches how the AI responds, and uses a *separate* AI "judge" to
score whether the trick worked. It learns from each attempt to get smarter, then hands
you a clear report: what held up, what broke, and how to fix it. Crucially, it can run
**entirely on your own computer**, so sensitive test content never leaves your control.
It's a way to make AI products provably safer before customers ever use them.

## 20. Developer Handover Summary

- **What it is:** A LangGraph state machine (`core/graph.py`) over a ~265-field
  `AuditorState` (`core/state.py`) that orchestrates LLM "roles" to red-team a target
  model and produce robustness reports. Three entry points (`main.py` CLI, `api.py`
  FastAPI, `dashboard.py` Streamlit) all drive the same graph.
- **Start here:** Read `PROJECT_DOCUMENTATION.md` and `ARCHITECTURE_REVIEW.md` (both
  current and detailed), then `core/graph.py`, `core/state.py`, and `config.py`. The
  scoring brain is `evaluators/evidence_aggregator.py`; the routing brain is
  `agents/analyst.py`.
- **Run it:** `python main.py --dry-run -o "..."` for a no-cost smoke test; default
  backend is **local Ollama** (must be running). Provider wiring must keep an `ollama`
  branch or it falls back to Mock.
- **Config model:** everything flows from `.env` → `PromptEvoSettings` (`config.py`), but
  **many behaviors are inline env flags** scattered in code — grep before changing
  behavior.
- **Persistence:** SQLite checkpointer (`checkpoints.db`) + optional Redis. **Never
  commit** `checkpoints.db*`; reducers in `core/state.py` (`replace_value`,
  `merge_branches`, etc.) exist specifically to prevent state-channel bloat — don't
  reintroduce `operator.add` on full lists.
- **Known traps:** routers mutate state (BUG-3, deferred); `should_continue` is a
  470-line guard stack; god-files are large; some tests fail pre-existingly; `.venv` is
  flaky on the OneDrive path (use a venv elsewhere).
- **Tests:** `pytest` (config in `pyproject.toml` excludes `scout/`). Touched-area
  baseline: ~77 pass, ~3 pre-existing failures.
- **Before shipping:** rotate any secrets in the on-disk `.env`, add CI/Docker, and gate
  the dashboard.

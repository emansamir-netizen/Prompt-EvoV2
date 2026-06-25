# Prompt-Evo Project Documentation

Prompt-Evo is a Python 3.11 framework for authorized AI safety auditing,
red/blue-team evaluation, and robustness reporting. It coordinates multiple
LLM roles, target adapters, evaluators, memory modules, and remediation logic
through a LangGraph state machine. The repository includes a CLI runner, a
FastAPI service, a Streamlit dashboard, persistence helpers, generated reports,
and a broad regression test suite.

> Use this project only for systems you own or are explicitly authorized to
> evaluate. The framework is designed for defensive assessment, model safety
> validation, and controlled research workflows.

## What This Project Does

Prompt-Evo runs an audit loop against a configured target model or mock target.
Each session starts from an audit objective, prepares candidate goals and seeds,
generates controlled probes, sends them to the target adapter, evaluates
responses, updates memory, optionally produces remediation suggestions, and
writes structured results.

The project supports:

- Multi-agent orchestration with LangGraph.
- CLI execution for local audit sessions.
- FastAPI execution for service and CI/CD integration.
- Streamlit dashboard monitoring.
- Multiple provider families through LangChain and local adapters.
- Mock/dry-run execution for development without external model calls.
- Scoring, response classification, goal alignment, and robustness reporting.
- Redis-backed or in-process audit persistence.
- Regression tests covering graph behavior, routing, scoring, API security,
  adapters, memory, reporting, and runtime bug fixes.

## Repository Layout

```text
.
|-- main.py                 # CLI runner for local Prompt-Evo sessions
|-- api.py                  # FastAPI service around the LangGraph workflow
|-- dashboard.py            # Streamlit command-center dashboard
|-- config.py               # Central settings object and LLM factories
|-- pyproject.toml          # Package metadata, dependencies, pytest config
|-- requirements.txt        # Pinned direct dependencies from local verification
|-- .env.example            # Environment template
|-- adapters/               # Target model adapter implementations
|-- agents/                 # Graph nodes that generate, route, and refine probes
|-- core/                   # Graph, state, routing guards, contracts, utilities
|-- evaluators/             # Judges, classifiers, scoring, evidence aggregation
|-- infra/                  # Security, persistence, observability, metrics
|-- memory/                 # Short-term, long-term, goal, strategy, and MCTS memory
|-- remediation/            # Guardrail and patch suggestion helpers
|-- reporting/              # Robustness report aggregation
|-- strategy/               # Strategy library and selection logic
|-- utils/                  # Shared utility helpers
|-- scout/                  # Legacy/offline seed and goal pipeline
|-- data/                   # Scenario, tactic, prompt, and memory data files
|-- config/                 # YAML runtime and persona configuration
|-- tests/                  # Pytest regression suite
|-- reports/                # Per-session generated reports
|-- artifacts/              # Generated/supporting artifacts
`-- scratch/, tmp/          # Experimental scripts and temporary outputs
```

Several log, trace, and patch files are present in the root directory. They
appear to be development evidence from earlier verification and repair passes,
not required source modules.

## Architecture Overview

The central orchestration lives in `core/graph.py`. It builds a LangGraph
`StateGraph` over `core.state.AuditorState`, then compiles it into the global
graph application imported by the CLI, API, and dashboard.

At a high level, a session moves through this lifecycle:

1. `scout_planner` performs offline preparation and seed/goal selection.
2. `scout` warms up or adjusts strategy when cooperation is low.
3. `analyst` chooses the next route, technique, and candidate branch.
4. `memory_retriever` can supply long-term memory hints.
5. `inquiry_swarm`, `gci`, or `rmce` generates or refines the next message.
6. Optional `hitl` pauses for human approval when enabled.
7. `target` sends the active message to the target adapter.
8. `response_classifier`, `self_referee`, and judge/scorer nodes evaluate the
   result.
9. `experience_pool` records what happened and updates learning state.
10. `goal_selector` and behavioral progression logic decide whether to continue.
11. `finalize_audit` and `reporter` produce final session outputs.

The state object is the common operating picture for the whole graph. It stores
message history, active goals, candidate branches, scores, status, memory
signals, target metadata, collected answers, remediation notes, and report data.

## Runtime Entry Points

### CLI: `main.py`

`main.py` is the local command-line runner. It loads `.env`, builds the
inquiryer LLM and target adapter, initializes the default state, then invokes or
streams the graph.

Supported CLI options:

```text
--objective, -o        Audit objective for the session
--target-model, -t     Target model override
--inquiryer-model, -a  Inquiryer model override
--session-id, -s       Explicit session UUID
--dry-run, -d          Use mock adapters and avoid real model calls
--stream, -S           Stream node-by-node output
--no-stream            Run graph in one call
```

### API: `api.py`

`api.py` exposes a FastAPI service suitable for external applications,
dashboards, and CI/CD gates. It wraps the same LangGraph workflow and adds API
authentication, model allowlisting, rate limiting when `slowapi` is installed,
session storage, metrics, and server-sent events.

### Dashboard: `dashboard.py`

`dashboard.py` is a Streamlit UI for starting and monitoring sessions. It keeps
session data in a process-level store that survives Streamlit reruns and can
display live progress, status, and reports.

## Installation

### Requirements

- Python 3.11 or newer.
- Optional Redis server for persistent session storage.
- Optional Ollama server for local model execution.
- Provider API keys if using OpenAI, Anthropic, Groq, OpenRouter, or similar
  external providers.

### Create an Environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Alternatively, install from `pyproject.toml`:

```powershell
pip install -e .
```

For tests:

```powershell
pip install -e ".[test]"
```

## Configuration

Copy the template and edit the values:

```powershell
Copy-Item .env.example .env
```

The main configuration is loaded by `config.py` into `PromptEvoSettings`.

| Area | Important Variables |
| --- | --- |
| Persistence | `REDIS_URL`, `REDIS_TTL_HOURS`, `REDIS_KEY_PREFIX` |
| API security | `PROMPTEVO_API_KEYS`, `PROMPTEVO_DEV_DISABLE_AUTH`, `ALLOWED_TARGET_MODELS` |
| Providers | `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GROQ_API_KEY`, OpenRouter variables |
| Inquiryer role | `INQUIRYER_PROVIDER`, `INQUIRYER_MODEL`, `INQUIRYER_TEMPERATURE` |
| Judge role | `JUDGE_PROVIDER`, `JUDGE_MODEL`, `JUDGE_TEMPERATURE` |
| Summariser role | `SUMMARISER_PROVIDER`, `SUMMARISER_MODEL` |
| Target role | `TARGET_PROVIDER`, `TARGET_MODEL`, target provider keys |
| Ollama | `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, timeout and generation limits |
| Memory | `FAISS_INDEX_PATH`, `GLTM_PATH`, `TLTM_ENABLED`, `EMBEDDING_MODEL` |
| Session limits | `TAP_MAX_DEPTH`, `TAP_BRANCHING_FACTOR`, `TAP_BEAM_WIDTH`, `MAX_SESSION_TURNS` |
| Scoring | `COOP_SCOUT_THRESHOLD`, `JUDGE_SUCCESS_THRESHOLD`, RAHS variables |
| Feature flags | `DRY_RUN`, `HITL_ENABLED`, `ENABLE_RED_DEBATE`, `STM_AUTO_COMPRESS` |

### LLM Roles

Prompt-Evo separates model roles to reduce evaluation bias:

- **Inquiryer LLM**: used by scout, swarm generation, decomposition,
  combination, and remediation helpers.
- **Judge LLM**: used by evaluation modules such as Prometheus-style judging
  and RedDebate-style evaluation.
- **Summariser LLM**: used by short-term memory compression.
- **Target model**: the model or mock system being audited.

### Security Validation

`infra/security.py` performs startup checks:

- Blocks placeholder API keys for protected endpoints.
- Rejects dev auth bypass in production.
- Validates target models against `ALLOWED_TARGET_MODELS`.
- Uses `X-PromptEvo-Key` for protected API routes.
- Supports constant-time API key comparison.

For local experiments without external providers, prefer `DRY_RUN=true` or the
CLI `--dry-run` flag.

## Running the Project

### Local Dry Run

```powershell
python main.py --dry-run --objective "Evaluate whether the target follows its stated safety policy"
```

Dry run uses mock adapters and is the safest way to verify the graph,
formatting, and report generation without external model calls.

### Local CLI With Configured Providers

```powershell
python main.py --objective "Run an authorized robustness check for the configured target"
```

The CLI reads provider settings from `.env`. Use `--target-model` and
`--inquiryer-model` to override model names for a single session.

### FastAPI Server

```powershell
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

Health check:

```powershell
curl http://localhost:8000/api/v1/health
```

Protected API calls require:

```text
X-PromptEvo-Key: <one value from PROMPTEVO_API_KEYS>
```

### Streamlit Dashboard

```powershell
streamlit run dashboard.py
```

The dashboard defaults to Streamlit's local port, commonly
`http://localhost:8501`.

## API Reference

The API is defined in `api.py`.

### `GET /api/v1/health`

Returns service health, observability status, and basic runtime information.

### `GET /api/v1/metrics`

Returns production metrics including session counts, success/failure data, and
effectiveness statistics. Requires API key authentication.

### `GET /api/v1/sys/topology`

Returns authenticated system topology and configured model allowlists.

### `GET /api/v1/graph-topology`

Returns a graph representation for visualization/debugging. Requires API key.

### `POST /api/v1/audit`

Starts an asynchronous audit session. Important request fields:

```json
{
  "objective": "Authorized robustness objective",
  "target_model": "mock-target",
  "inquiryer_provider": "",
  "inquiryer_model": "",
  "target_provider": "",
  "block_threshold": null,
  "dry_run": true
}
```

When `block_threshold` is set, the API can behave as a CI/CD gate and reject
results whose final risk score exceeds the threshold.

### `GET /api/v1/audit/{session_id}`

Polls the current status and final report, if available.

### `GET /api/v1/audit/{session_id}/stream`

Streams live session events using server-sent events.

### `GET /api/v1/sessions`

Lists sessions known to the active server/store.

## Dashboard

The dashboard offers a web interface for running and observing audits. It is
implemented as a single Streamlit app with custom CSS and a process-level audit
store.

Key behavior:

- Starts sessions without using subprocesses.
- Tracks background session execution.
- Displays live events and result summaries.
- Supports human-in-the-loop flow when the graph requests approval.
- Uses `infra.observability.configure_logging()` for structured logs.

## Reports and Artifacts

The graph writes per-session outputs under:

```text
reports/{session_id}/
```

Common files include:

- `summary.json`
- `structured_log.json`
- `robustness_report.json`
- `payloads.json` or `messages.json`
- `full_transcript.md`

`reporting/robustness_report.py` aggregates final `AuditorState` data into a
structured report with:

- Overall verdict.
- Counts of successful, partial, failed, and inconclusive goals.
- Findings by goal.
- Repeated defense patterns.
- Effective techniques.
- Suggested remediation summary fields.
- Memory and MCTS update counts.

## Testing

The repository has 92 pytest files under `tests/`. The `pyproject.toml`
configuration limits test discovery to `tests/` and excludes the legacy
`scout/` pipeline from pytest collection.

Run the full suite:

```powershell
pytest
```

Run a focused test:

```powershell
pytest tests/test_api_security.py
```

Useful test areas:

- API security and model allowlisting.
- Adapter failure paths.
- Graph routing and loop-control regression tests.
- Prompt/message/payload contract validation.
- Goal alignment and goal locking.
- Memory contamination and storage.
- Robustness report generation.
- Dashboard rendering checks.
- Provider configuration unification.

## Core Concepts

### `AuditorState`

`core/state.py` defines `AuditorState`, a large `TypedDict` passed between all
graph nodes. It is intentionally JSON-friendly so sessions can be persisted,
streamed, and reported without embedding live model objects.

### TAP-Style Branching

The state tracks candidate branches, depth, scores, pruning status, and
off-topic similarity. The analyst and evaluator modules use these fields to
keep exploration controlled and auditable.

### PAP/Technique Rotation

Technique fields track which strategy is active, which approaches were pruned,
and which approaches performed well. Strategy selection modules and the
experience pool use this feedback across turns.

### Multi-Turn Decomposition

The decomposer and combiner support workflows where an objective is split into
smaller sub-questions, evaluated separately, and then summarized. This is routed
through the same target and judge pipeline.

### Memory Layers

- `memory/stm.py`: short-term memory and compression.
- `memory/tltm.py`: long-term tactical memory.
- `memory/gltm.py`: guardrail memory.
- `memory/experience_pool.py`: turn-level result logging.
- `memory/mcts_memory.py`: MCTS-style goal/seed memory.
- `memory/strategy_bandit.py`: strategy performance selection.

### Evaluators

Evaluator modules classify target replies, score risk and alignment, aggregate
evidence, detect drift/off-topic behavior, and decide whether a result is
successful, partial, failed, or inconclusive.

### Adapters

Adapters isolate target model invocation:

- `adapters/base_adapter.py`: common protocol and mock adapter.
- `adapters/langchain_adapter.py`: LangChain-backed target calls.
- `adapters/ollama_adapter.py`: local Ollama target calls.
- `adapters/multimodal_adapter.py`: multimodal adapter support.

## Development Notes

The package is named `prompt_evo` with version `2.0.0`. The project requires
Python `>=3.11`.

`pyproject.toml` configures Ruff with:

```toml
line-length = 100
target-version = "py311"
```

Important source files:

- `core/graph.py`: graph construction and routing.
- `core/state.py`: state schema and reducers.
- `config.py`: settings and model factories.
- `infra/security.py`: API auth and startup secret validation.
- `infra/persistence.py`: Redis/in-memory persistence helpers.
- `infra/metrics.py`: runtime metrics registry.
- `evaluators/evidence_aggregator.py`: decision aggregation.
- `reporting/robustness_report.py`: final report builder.

Avoid committing local secrets, `.env`, transient logs, caches, and generated
session outputs unless intentionally preserving an audit artifact.

## Troubleshooting

### Startup Fails Because of Placeholder Secrets

Replace placeholder values in `.env`, especially `PROMPTEVO_API_KEYS` and any
active provider credentials. For local non-provider execution, set `DRY_RUN=true`
or pass `--dry-run`.

### Protected API Routes Return 401 or 503

Ensure `PROMPTEVO_API_KEYS` contains at least one non-placeholder value and send
it using:

```text
X-PromptEvo-Key: <key>
```

Do not rely on `PROMPTEVO_DEV_DISABLE_AUTH=true` in production.

### Target Model Rejected

Add the model name to `ALLOWED_TARGET_MODELS`, or use `mock-target` for dry-run
testing.

### Redis Not Available

The persistence layer is designed to fall back to in-process storage where
supported, but production use should configure Redis.

### External Provider Calls Fail

Check the relevant provider, key, model name, timeout, and target-provider
variables. For Ollama, confirm the local server is running at `OLLAMA_BASE_URL`.

### Tests Accidentally Collect `scout/`

Use the included `pyproject.toml` pytest configuration. It sets:

```toml
norecursedirs = ["scout", ".venv", "build", "dist", "tmp"]
testpaths = ["tests"]
```

## Security Notes

- This repository can generate, evaluate, and log sensitive model-audit content.
- Keep `.env`, generated transcripts, and report artifacts private unless they
  have been reviewed.
- Use allowlists for target models in shared environments.
- Keep API authentication enabled outside isolated local development.
- Prefer dry-run mode when validating installation or graph behavior.
- Run audits only against systems where you have explicit permission.

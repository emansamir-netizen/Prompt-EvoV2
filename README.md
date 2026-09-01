# PromptEvo

**A multi-agent red-teaming and safety assessment platform for large language models.**

PromptEvo generates adversarial prompts, adapts them based on how a target model responds, and scores the results through a judging layer that is kept structurally independent from the components producing the attacks. Every verdict carries the evidence that produced it, so a score can be audited rather than trusted.

Built in Python 3.11 with LangGraph. Runs against locally hosted models and hosted APIs through a common adapter layer.

---

## Why this exists

Most LLM red-teaming tooling has the same weakness: the system that generates an attack also decides whether it succeeded. That produces scores nobody can check. A confident-sounding refusal gets graded as a success, and the number goes into a report.

PromptEvo separates the two. The attack side and the judging side never share state, and a verdict is only issued when the evidence supporting it is present in the response. The design goal was not a higher attack success rate — it was a number a reader can verify.

---

## Architecture

The pipeline runs in eight stages, with twelve coordinated agents.

```
RECON        Scout Planner → Scout
STRATEGY     Analyst → HIVE MIND
GOAL         Goal Selector → Goal Rotation → Decomposer
ATTACK       Probe Optimizer → GCI → RMCE → Combiner
DELIVERY     Self Referee → target adapter
EVALUATION   Refusal Filter → Judge → RAHS Scorer → Evidence Aggregator
LEARNING     Experience Pool → Memory Retriever → Context Aggregator
OUTPUT       Remediation → Reporter
```

### Reconnaissance and planning

| Component | Role |
|---|---|
| **Scout Planner** | Offline phase: detects the target's domain, profiles likely weaknesses, generates audit goals, creates seed prompts, and ranks them using Monte Carlo tree search. |
| **Scout** | Live adaptive reconnaissance. Probes the model and feeds observed behaviour back into planning. Strategies: Epistemic Depth, Role Inversion, Domain Authority. |

### Attack layer

| Component | Role |
|---|---|
| **Analyst** | Central routing component. Inputs: audit objective, response classification, judge score, RAHS score, prior attempts, memory retrieval, turn number. Routes to the appropriate attack path. |
| **HIVE MIND** | Executes multiple attack strategies in parallel and compares outcomes. |
| **Decomposer** | Breaks a goal into sub-goals when a direct approach is refused. |
| **GCI** | Activates after two refusals. Reframes the request rather than repeating it. |
| **RMCE** | Activates after three or more refusals. Recursive multi-turn prompting. |
| **Self Referee** | Validates each probe before it is sent. Kept independent of the Judge so that pre-send filtering does not bias post-response scoring. |

### Evaluation layer

| Component | Role |
|---|---|
| **Refusal Filter** | Early exit for clear refusals, so obvious cases never reach the expensive judging path. |
| **Judge** | Model-based evaluation against written criteria on a 0–5 compliance scale. |
| **RAHS Scorer** | Harm scoring, independent of the compliance score. |
| **Evidence Aggregator** | Collects the spans of the response that justify a verdict. A verdict without supporting evidence is not issued. |
| **RedDebate** | Contested cases are resolved through Advocate, Defender and Socratic roles arguing against the written criteria rather than being decided by a single score. |

**A 5/5 compliance score does not automatically mean a successful jailbreak.** The criteria define what evidence is required at each verdict level, and the artifact gate below enforces it.

### ContentSafetyOverride

The central design contribution of the project. Verdicts are artifact-gated: a response is judged on what the model actually produced, not on how it phrased its willingness. A model that agrees enthusiastically and then produces nothing does not score as a success.

### Memory

Six layers feeding a single context window through a Memory Retriever and Context Aggregator:

- **STM** — short-term working state within a session
- **Experience Pool** — outcomes of prior attempts
- **TLTM** — tactical long-term memory
- **MCTS Strategy Memory** — ranked strategy performance across runs
- **GLTM** — observed guardrail behaviour per target
- **Diagnostic Failure Memory** — what failed and why, kept separately from what succeeded

---

---

## Requirements

- Python 3.11 or newer
- Git
- `pip`

## Setup

```bash
# 1. Create a virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure providers
cp .env.example .env               # Windows: copy .env.example .env
```

Edit `.env` and set your provider API keys and model settings. Adapters are available for Ollama, OpenAI, Groq and other providers, so the platform can run fully locally against an Ollama model with no external API calls.

## Running

```bash
python main.py --help              # available options
python main.py                     # run the audit engine
```

### API

`api.py` exposes the engine as a service for integration and adapter registration.

### Interfaces

PromptEvo ships three interfaces. Two of them are in this repository:

- **CLI** — `main.py`, the primary entry point.
- **Streamlit dashboard** — `dashboard/streamlit_app.py`. This was the first interface built, kept in the repository as a lightweight way to review sessions and explore reports without running the full stack.

  ```bash
  streamlit run dashboard/streamlit_app.py
  ```

  Optional dependencies: `pip install -r dashboard/requirements-dashboard.txt`

- **React dashboard** — the primary interface used for the final submission, running against the FastAPI service. It is **not published in this repository**; only the engine, the API and the Streamlit interface are. If you are evaluating the frontend work specifically, ask and it can be shared separately.

---

## Project layout

```
agents/        agent modules and runtime logic
scout/         reconnaissance and planning
strategy/      attack strategy selection and MCTS ranking
probes/        probe construction and optimisation
evaluators/    judge, scoring and evidence aggregation
memory/        the six memory layers and retrieval
remediation/   remediation generation from findings
reporting/     report construction
reports/       generated reports
adapters/      model provider adapters
core/          orchestration, state and engine internals
dashboard/     Streamlit interface and UI components
infra/         infrastructure and runtime support
config/        configuration
data/          datasets, prompts and local model resources
tests/         test suite
utils/         shared utilities
```

## Testing

```bash
pytest
```

106 tests, 101 passing at the time of the final project submission. The five failures are documented below rather than hidden.

---

## Known limitations

Published deliberately. A tool that audits other systems should be honest about its own state.

- **`core/graph.py` is roughly 4,100 lines.** Orchestration logic that should be split across modules has accumulated in one file. It works, but it is the main obstacle to anyone extending the pipeline.
- **`evaluators/evidence_aggregator.py` is precedence-sensitive.** The order in which evidence rules are applied changes the outcome in some edge cases. This is a correctness risk, not just a style issue.
- **Five failing tests** remain out of 106. They are known, not silent.
- **The agent layer is thinner than the architecture implies in places.** Some components documented above are more lightly implemented than others.
- **The frontend is bound more tightly to specific providers than it should be.** Generic API connectivity would be the right shape.
- **The React dashboard is not in this repository.** The published tree covers the engine, the API and the Streamlit interface only, so a reader cannot review the frontend work from here.

---

## Security notes

- Never commit `.env`, `.venv/`, runtime reports or local logs. `.gitignore` covers these.
- `.env.example` ships placeholder configuration only.
- `data/audit_runs/` and `data/memory/` hold runtime output and are ignored.
- This is an auditing tool intended for testing systems you own or are authorised to test.

---

## Team and contributions

PromptEvo was submitted as a graduation project at the Faculty of Artificial Intelligence, Menoufia University, supervised by Prof. Osama Abdel Raouf. Final grade: 96/100.


**This fork is maintained by [Eman Mohamed Samir ElNowehy](https://www.linkedin.com/in/eman-elnowehy-7b5183296). 

---

## Background reading

The design draws on published work in automated red-teaming and multi-agent defence: RedAgent, AutoDefense, and Papillon.

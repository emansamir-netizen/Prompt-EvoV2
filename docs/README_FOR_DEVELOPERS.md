# PromptEvo — Developer README

> A fast-orientation guide for developers working on PromptEvo, the automated LLM red-teaming framework. For the full architecture reference (file-by-file, import sweep, node/routing tables) see **[`PROJECT_STRUCTURE_AND_ARCHITECTURE.md`](./PROJECT_STRUCTURE_AND_ARCHITECTURE.md)**.
>
> Documentation/architecture level only — no operational attack content. PromptEvo is a defensive tool for authorized red-team evaluation.

---

## What it is, in one minute

PromptEvo runs an *attacker* LLM ("Inquiryer") against a *target* LLM across a multi-turn conversation on **LangGraph**. Every response is scored by a layered evaluation stack that distinguishes a **real harmful artifact** from a *simulated*/*defensive*/*elicitation* answer. The run ends with a per-session report and a blue-team defense patch.

- **Entry points:** `main.py` (CLI), `api.py` (FastAPI), `dashboard.py` (Streamlit), `config.py` (LLM factory).
- **Engine:** `core/graph.py` (the LangGraph) over `core/state.py` (`AuditorState`).
- **Attacker model** (`INQUIRYER_MODEL`) must be **uncensored/abliterated**, or the attack pipeline self-refuses.
- **Default backend:** local **Ollama**.

---

## 1. High-Level Architecture

Everything routes through the core engine; agents and evaluators communicate only via shared state, and adapters are the only components that make external LLM calls.

```mermaid
flowchart TD
    U["User / CLI / API / Dashboard"]
    EP["Entry Points<br/>main.py · api.py · dashboard.py"]
    CFG["config.py<br/>LLM factories — 3 roles"]
    CORE["Core Orchestration<br/>graph.py + state.py + routing/guards"]
    ADAPT["LLM Adapters<br/>ollama · langchain · base"]
    AGENTS["Agents Layer"]
    EVAL["Evaluators Layer"]
    MEM["Memory Layer"]
    REPORT["Reporting Layer"]
    DATA["Data and Config<br/>question_set.csv · scenarios · yaml"]
    OUT["Session Reports<br/>reports/session-id/*"]

    U --> EP
    EP --> CFG
    EP --> CORE
    CFG --> ADAPT
    DATA --> CORE
    CORE --> AGENTS
    CORE --> EVAL
    CORE --> MEM
    CORE --> REPORT
    AGENTS --> ADAPT
    AGENTS --> CORE
    EVAL --> CORE
    MEM --> CORE
    REPORT --> OUT
```

The three LLM roles (Inquiryer / Judge / Summariser) are deliberately separate to avoid evaluation bias — all configured in `config.py` from `.env`.

---

## 2. Runtime Audit Flow

### Main loop

`scout_planner` runs once; the loop is `scout → target → classifier → judge → (pool / remediation) → memory_retriever → analyst → scout …`, ending at `reporter`.

```mermaid
flowchart TD
    SP["scout_planner — entry"] --> SC["scout"]
    SC --> TG["target"]
    TG --> RC["response_classifier"]
    RC --> JU["judge_and_score<br/>Prometheus + RAHS + aggregator + seal"]
    JU -->|in progress| POOL["experience_pool"]
    JU -->|success| REM["remediation — patch gen"]
    JU -->|budget exhausted| REP["reporter"]
    REM --> POOL
    POOL -->|retry| MR["memory_retriever"]
    POOL -->|terminate| REP
    MR --> AN["analyst (router)"]
    AN -->|next probe| SC
    AN -->|terminate| REP
    REP --> E(["END"])
```

Hard refusals are fast-pathed (judge skipped, score 1.0).

### Analyst routing branches (conditional)

The analyst can divert to specialized agents under specific conditions (see the architecture doc §15/§16 for exact triggers).

```mermaid
flowchart TD
    AN["analyst (router)"]
    TG["target"]
    AN -->|multi-branch generation| IS["inquiry_swarm"]
    AN -->|guarded goal| DEC["decomposer"]
    AN -->|refusals + academic framing| GCI["gci"]
    AN -->|heavy refusals + academic| RMCE["rmce"]
    IS --> TG
    DEC --> TG
    GCI --> TG
    RMCE --> TG
    TG -->|first turn, depth 0| SR["self_referee"]
    SR --> AN
    TG -->|all sub-questions answered| COM["combiner"]
    COM --> JU["judge_and_score"]
```

`self_referee` runs once/session; `decomposer`+`combiner` only in decomposition mode; `gci`/`rmce` only on the matching `target_defense_profile` pattern.

---

## 3. Component Map

Runtime-critical files grouped by folder, with the high-level call direction.

```mermaid
flowchart LR
    subgraph Core["core/"]
        G["graph.py"]
        S["state.py"]
        SL["score_lifecycle.py"]
    end
    subgraph Agents["agents/"]
        SP["scout_planner"]
        SC["scout"]
        TG["target"]
        AN["analyst"]
        HM["hive_mind"]
    end
    subgraph Eval["evaluators/"]
        RClf["response_classifier"]
        EA["evidence_aggregator"]
        PM["prometheus + rahs"]
    end
    subgraph Mem["memory/"]
        TLTM["tltm"]
        EPL["experience_pool"]
    end
    subgraph Adp["adapters/"]
        OL["ollama"]
        BA["base"]
    end
    subgraph Out["remediation/ + reporting/ + reports/"]
        PG["patch_generator"]
        RR["robustness_report"]
        OUT["session-id/*"]
    end

    G --> SP
    G --> AN
    SP --> SC --> TG
    TG --> OL
    TG --> RClf --> EA
    EA --> EPL
    EPL --> TLTM
    AN --> HM
    EA --> PG --> RR --> OUT
```

---

## 4. State & Verdict Lifecycle

How one response becomes a sealed verdict. The **ContentSafetyOverride** is the decisive fork between a confirmed jailbreak, an elicitation/partial, and inert output.

```mermaid
flowchart TD
    TR["target response"] --> RC["response_classifier<br/>coarse class"]
    RC -->|hard refusal| LOW["fast-path score = 1.0"]
    RC -->|else| JU["Prometheus judge<br/>0–5"]
    JU --> RAHS["RAHS scorer<br/>0–10 harm"]
    RAHS --> EA["evidence_aggregator"]
    LOW --> EA
    EA --> CSO{"actionable<br/>artifact produced?"}
    CSO -->|yes| CONF["ContentSafetyOverride<br/>confirmed jailbreak · ASR=1"]
    CSO -->|engaged, no artifact| ELIC["elicitation<br/>partial_success"]
    CSO -->|no| BASE["status from judge / classifier"]
    CONF --> SEAL["ScoringSeal"]
    ELIC --> SEAL
    BASE --> SEAL
    SEAL --> FA["analyst SuccessGuardFinal<br/>+ reporter re-aggregate"]
    FA --> OUT["final status + ASR"]
```

When changing scoring, the danger zone is `evaluators/evidence_aggregator.py`, `core/score_lifecycle.py`, and the analyst success-gating — unit-test before/after.

---

## 5. Reports Output

Each run writes four artifacts; a defense patch goes to GLTM on success.

```mermaid
flowchart LR
    RUN["audit run"] --> DIR["reports/session-id/"]
    DIR --> FT["full_transcript.md<br/>human-readable"]
    DIR --> RR["robustness_report.json<br/>machine / CI-CD"]
    DIR --> SL["structured_log.json<br/>debugging"]
    DIR --> SM["summary.json<br/>aggregation"]
    RUN -. on success .-> GLTM["defense patch<br/>data/memory/gltm_guardrails.yaml"]
```

---

## 6. Runtime vs Non-Runtime Code

Only the first two groups run during an audit. The rest are dormant (flag-gated), standalone, alias shims, scratch, or dead — confirmed by an importer sweep (architecture doc §17).

```mermaid
flowchart TB
    subgraph CR["Core runtime"]
        A["graph.py · state.py · score_lifecycle.py"]
        B["agents: scout_planner · scout · target · analyst · hive_mind"]
        C["evaluators · memory · base/ollama adapters"]
        D["agents/probe_optimizer.py — real module"]
    end
    subgraph CO["Conditional runtime"]
        E["self_referee · gci · rmce · decomposer · combiner"]
    end
    subgraph FG["Flag-gated / dormant"]
        F["goal_cursor · finalize_audit — AUDIT_MODEL_V2=false"]
        H["hitl_review — HITL_ENABLED=false"]
    end
    subgraph ST["Standalone — not a graph node"]
        I["scout/ pipeline — only unified_llm_client used lazily"]
    end
    subgraph SH["Back-compat alias shims"]
        J["red_debate_swarm.py → runtime via graph"]
        K["7 shims → tests-only"]
        L["domain_detector · profiler · scenario_generator → dead"]
    end
    subgraph GEN["Scratch / generated"]
        M["patch*.py · test_mutation*.py · *.log · reports/**"]
    end
    subgraph DEAD["Dead / unreferenced"]
        N["adapters/multimodal_adapter.py"]
    end
```

**Key facts (strict, from the sweep):**
- The loose `agents/*.py` files are **back-compat alias shims** (`sys.modules` re-exports of the subpackages), **not duplicate code**. Only `red_debate_swarm.py` is on a runtime path.
- `adapters/multimodal_adapter.py` is **dead** — no importer anywhere; the `"multimodal"` flag elsewhere is a passive descriptor, not a switch that loads it.
- The standalone `scout/` directory is **not** a LangGraph node; only `scout.unified_llm_client` is imported (lazily) by `evaluators/hybrid_judge.py`.
- `AUDIT_MODEL_V2` nodes (`goal_cursor`, `finalize_audit`) are **dormant** by default.

---

## 7. Get Running

```bash
cp .env.example .env     # set TARGET_MODEL / INQUIRYER_MODEL / judge / classifier (local Ollama default)
python main.py           # run one audit (CLI)
uvicorn api:app --port 8000   # optional REST + SSE + CI/CD gate
streamlit run dashboard.py    # optional war-room UI
```

Then open the newest `reports/<session_id>/full_transcript.md` (human) and `robustness_report.json` (machine).

**Read these first when modifying the engine:** `config.py` → `core/state.py` → `core/graph.py` → `evaluators/evidence_aggregator.py` → `agents/analyst/__init__.py` → `memory/experience_pool.py`.

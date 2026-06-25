# Current Architecture Audit

Phase 1 audit only. No runtime logic was changed.

## Files Reviewed

- `core/state.py`
- `core/graph.py`
- `agents/scout.py`
- `agents/analyst.py`
- `agents/injector.py`
- `agents/target.py`
- `evaluators/response_classifier.py`
- `evaluators/evidence_aggregator.py`
- `memory/experience_pool.py`
- `memory/tltm.py`
- `reporting/robustness_report.py`
- `dashboard.py`
- `main.py`
- `config.py`
- `PROJECT_DOCUMENTATION.md`

## Requested State Fields

| Field | Present? | Notes |
|---|---:|---|
| `current_goal` | no | Equivalent concept exists as `active_goal`, but the requested canonical name is absent. |
| `goal_id` | partial | Used inside goal dicts and reports, but not declared as a top-level state field. Top-level state uses `active_goal_id`. |
| `goal_locked` | yes | Declared and initialized through goal lifecycle fields. |
| `target_history` | no | Target responses are stored in `messages`, `last_target_response`, and sometimes `target_responses` references, but no canonical `target_history` field exists. |
| `active_strategy` | no | Strategy exists through `active_persuasion_technique`, `technique_reason`, `analyst_directives`, and route decisions. |
| `response_class` | yes | Set by `response_classifier_node` and consumed by judge, analyst, aggregator, report/dashboard paths. |
| `judge_result` | no | Judge output is split across `prometheus_score`, `latest_feedback`, `judge_parse_mode`, `judge_confidence`, `compliance_type`, and aggregator fields. |
| `memory_hits` | partial | `turn_trace` doc mentions memory hits, and memory data is exposed through `tltm_context`, `recommended_next`, and `avoid_next`; no scalar/list named `memory_hits`. |
| `termination_reason` | partial | Reporter writes termination reason into `structured_log.json`; no persistent top-level state field named `termination_reason`. |

## Component Audit Table

| Component | موجود؟ | شغال؟ | المشكلة | التعديل المطلوب |
|---|---|---|---|---|
| State | yes | partial | Goal, strategy, judge, memory, and termination concepts exist, but several requested canonical names are missing; concept/evidence fields are distributed rather than explicit. | Add compatibility fields: `current_goal`, `goal_id`, `target_history`, `active_strategy`, `judge_result`, `memory_hits`, `termination_reason`, plus explicit concept/evidence buffers if Phase 2 needs them. |
| Graph | yes | yes | Requested nodes exist, but graph has additional routing complexity: decomposer, combiner, remediation, HITL, self-referee, GCI, RMCE, goal cursor, finalize audit, behavioral advance. Routing is mixed between `route_decision`, `next_route`, classifier gates, and V2 `analyst_decision`. | Document canonical route contract and, if needed, normalize routing around structured `analyst_decision` plus explicit terminal reasons. |
| Scout | yes | partial | Scout repairs active goal from `goal_suite`, generates probes, and handles warm-up. It reads prior responses from `messages`/`target_responses`, but no canonical `target_history` is maintained. | Add or populate `target_history` consistently from target responses and scout observations. |
| Analyst | yes | partial | Analyst now emits structured `analyst_decision`, but legacy state fields still drive much of the graph (`route_decision`, `next_route`, technique fields). Decision is present but not the only enforced source of truth. | Make `analyst_decision` the primary decision contract, keep legacy fields as derived mirrors, and reject incomplete/invalid decisions at the boundary. |
| Injector / Inquiry | yes | partial | `agents/injector.py` can produce structured `current_message`, but graph currently routes to `inquiry_swarm` as the injector-like generation step; naming is inconsistent. | Clarify whether `inquiry_swarm` is the production injector, then align node naming/docs and state outputs. |
| Target | yes | yes | Target trusts `current_message`, writes `last_target_response`, finish reason, alignment, and active goal id. It does not append to a canonical `target_history`. | Append normalized target exchange records into `target_history` with message, response, finish reason, goal id, and strategy. |
| Response Classifier | yes | yes | Classifier is strong and includes 5-class taxonomy, simulated compliance checks, target defense profile updates, and classifier signals. Some downstream docs still describe old 3-class behavior. | Keep 5-class taxonomy canonical and update docs/state comments where they still imply only 3 classes. |
| Judge / Evidence Aggregator | yes | partial | Aggregator provides hard gates for simulated compliance, infrastructure failures, refusals, alignment, parser reliability, and success demotion. But no single `judge_result` object captures the final decision. | Emit `judge_result` as a structured summary of score, status, reliability, evidence, failure reason, and gates triggered. |
| Memory | yes | partial | Experience pool stores success/failure, failure reason, compliance type, alignment, reasoning depth, response, and target model. Retrieval is still primarily vector similarity plus UCB over records; concept-level memory is not explicit. | Add concept/outcome memory fields such as concepts, evidence tags, failure concepts, and strategy-outcome mappings. |
| Report | yes | partial | Project writes `summary.json`, `structured_log.json`, `full_transcript.md`, and V2 can attach `audit_report`; docs mention `robustness_report.json`, `payloads.json`/`messages.json`. Current report includes evidence and why fields but not explicit concept reasoning throughout. | Add concepts, evidence gates, `judge_result`, `analyst_decision`, memory hits, and termination reason to final report artifacts. |
| Dashboard | yes | partial | Dashboard surfaces technique reason, finish reason, reasoning depth score, judge parse mode, recommended/avoid memory hints, and TLTM context. It does not expose canonical concept memory or `judge_result`. | Add panels for structured decision, judge gates, memory hits, target history, and concept/evidence timeline. |
| Main / Config | yes | yes | `main.py` guarantees final report writing on normal, interrupted, and exception exits. `config.py` has model/judge thresholds and provider resolution. No central config for the requested new state contract. | Add config toggles for strict structured analyst routing, hard success gates, and concept/outcome memory if introduced later. |

## Routing Summary

Current entry point is `scout_planner`, then `scout`.

Main path:

1. `scout_planner` -> `scout`
2. `scout` -> `target` only when a probe is explicitly queued, otherwise `analyst` or `reporter`
3. `analyst` -> `scout`, `decomposer`, `inquiry_swarm`, `gci`, `rmce`, `response_classifier`, `goal_selector`, `goal_cursor`, `finalize_audit`, `behavioral_advance`, or `reporter`
4. `inquiry_swarm` -> `target` or `hitl_review`
5. `target` -> `response_classifier`, `combiner`, `target`, `analyst`, `self_referee`, `rmce`, or `reporter`
6. `response_classifier` -> `judge_and_score`
7. `judge_and_score` -> `experience_pool`, `self_play_remediation`, or `reporter`
8. `experience_pool` -> `memory_retriever` or `reporter`
9. `memory_retriever` -> `analyst`
10. `finalize_audit` -> `reporter` -> `END`

## Key Findings

- The project is already beyond a simple linear pipeline; it has several loop guards and hard gates.
- Structured analyst decision exists in `agents/analyst_decision.py` and is emitted by `agents/analyst.py`, but legacy routing fields still matter.
- Fake success is partially addressed: `response_classifier.py`, `_judge_and_score_node`, `evidence_aggregator.py`, and `experience_pool.py` all contain simulated-compliance and zero-insight protections.
- Memory is richer than outcome-only storage, but not yet concept/outcome memory. It stores metadata and failure reasons, then retrieves by semantic similarity and UCB.
- Reporting exists, but the strongest reasoning/evidence objects are not consistently serialized into the final artifacts.

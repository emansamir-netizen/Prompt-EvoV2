from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum


@dataclass
class PhaseResult:
    """Fail-fast contract for all agent nodes.

    Every agent phase (scout, analyst, injector, judge, memory) MUST return
    a PhaseResult.  If ``ok`` is False, the graph router immediately routes
    to the error handler rather than propagating garbage data through the
    pipeline.

    Usage::

        result = PhaseResult(ok=True, phase="analyst", data={"cooperation_score": 0.7})
        if not result.ok:
            logger.error("[%s] FAILED: %s", result.phase, result.error)
            return {"inquiry_status": "error", "failure_reason_category": result.error}
    """
    ok: bool
    phase: str                          # "scout" | "analyst" | "injector" | "judge" | "memory"
    data: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    error_type: str = ""                # "connectivity" | "parse" | "validation" | "timeout"
    recoverable: bool = True            # False → terminate session immediately


class FollowUpStatus(Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    GENERATION_FAILED = "generation_failed"
    PROVIDER_ERROR = "provider_error"
    EMPTY_OUTPUT = "empty_output"

@dataclass
class FollowUpResult:
    status: FollowUpStatus
    prompts: List[str] = field(default_factory=list)
    strategy_tag: str = ""
    progression_level: int = 0
    mutation_source: str = ""
    reasoning: str = ""
    raw_output: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_usable(self) -> bool:
        return self.status in (FollowUpStatus.SUCCESS, FollowUpStatus.PARTIAL) \
               and len(self.prompts) > 0

    @property
    def should_progress(self) -> bool:
        return self.status == FollowUpStatus.GENERATION_FAILED

@dataclass
class AnalystVerdict:
    cooperation_score: float          # 0.0–1.0
    refusal_score: float              # 0.0–1.0
    insight_score: float                 # 0.0–1.0  — did the target revelation ANY protected info
    partial_compliance_score: float   # 0.0–1.0  — hedged or indirect disclosure
    deflection_score: float           # 0.0–1.0  — verbose non-answer
    topic_drift_score: float          # 0.0–1.0  — answer drifted from probe intent
    boundary_softness: float          # 0.0–1.0  — how firm was the refusal
    raw_response: str = ""
    revealed_fragments: List[str] = field(default_factory=list)
    recommended_next: str = ""        # "progress" | "pivot" | "decompose" | "repeat_mutated" | "terminate"
    confidence: float = 0.0
    reasoning: str = ""

@dataclass
class DecomposerResult:
    status: str                       # "success" | "parse_failure" | "generation_failure" | "unsafe_refused"
    sub_questions: List[str] = field(default_factory=list)
    original_intent: str = ""
    decomposition_strategy: str = ""  # "innocent_fragments" | "context_building" | "role_split" | "temporal_scatter"
    validation_errors: List[str] = field(default_factory=list)
    raw_output: Optional[str] = None

@dataclass
class ProviderResponse:
    content: str = ""
    is_empty: bool = False
    is_refusal: bool = False
    is_provider_error: bool = False
    done_reason: str = ""
    model: str = ""
    latency_ms: float = 0.0
    raw_metadata: Dict[str, Any] = field(default_factory=dict)
    error_type: Optional[str] = None  # "timeout" | "empty_content" | "malformed" | "connection" | None
    error_detail: Optional[str] = None

@dataclass
class MemoryEntry:
    target_id: str
    domain_key: str
    strategy_tag: str
    outcome_type: str
    reward: float
    prompts_used: List[str] = field(default_factory=list)
    response_summary: str = ""
    insight_fragments: List[str] = field(default_factory=list)
    run_mode: str = "production"         # "production" | "dev" | "test"
    is_trusted: bool = True
    provenance: str = ""
    created_at: str = ""
    ttl_hours: float = 168.0             # default 7 days

@dataclass
class RunReport:
    run_id: str
    target_id: str
    total_turns: int
    max_turns: int
    true_termination_reason: str
    provider_health: str                 # "healthy" | "degraded" | "failed"
    parser_health: str
    routing_health: str
    memory_health: str
    strategies_attempted: List[str] = field(default_factory=list)
    strategies_succeeded: List[str] = field(default_factory=list)
    insight_fragments_collected: List[str] = field(default_factory=list)
    refusal_count: int = 0
    partial_compliance_count: int = 0
    full_compliance_count: int = 0
    provider_errors: int = 0
    parser_errors: int = 0
    repetition_detected: bool = False
    progression_ceiling_reached: bool = False
    turns_detail: List[Dict[str, Any]] = field(default_factory=list)

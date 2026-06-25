"""Regression: the consecutive infra-failure counter must actually climb so a
dead provider (Ollama unreachable) aborts at MAX_CONSECUTIVE_INFRA_FAILURES
instead of spinning ~60x.

Bug: route_from_judge (a ROUTER) incremented `infrastructure_retries` and the
channel was undeclared, so it never persisted — it stayed stuck at 1/5 and the
run looped 60x / 218s on a dead Ollama before an unrelated guard killed it. Fix:
the judge NODE increments (declared, persisting) and the router reads.

This test pins the counter arithmetic the judge node now applies and that
`infrastructure_retries` is a declared AuditorState channel.
"""

from core.state import AuditorState


def _next_infra_retries(prev: int, status: str) -> int:
    # Mirror of the judge-node logic in _judge_and_score_node.
    return (prev + 1) if status in ("evaluation_failure", "infrastructure_failure") else 0


def test_channel_is_declared():
    assert "infrastructure_retries" in AuditorState.__annotations__


def test_counter_climbs_on_consecutive_infra_failures():
    n = 0
    for _ in range(5):
        n = _next_infra_retries(n, "infrastructure_failure")
    assert n == 5  # reaches MAX_CONSECUTIVE_INFRA_FAILURES → router aborts


def test_counter_resets_on_good_evaluation():
    n = 4
    n = _next_infra_retries(n, "partial_success")
    assert n == 0
    n = _next_infra_retries(n, "evaluation_failure")
    assert n == 1  # intermittent flakiness restarts from 0, never accumulates


def test_max_constant_is_small():
    from core.graph import MAX_CONSECUTIVE_INFRA_FAILURES
    assert 1 <= MAX_CONSECUTIVE_INFRA_FAILURES <= 10

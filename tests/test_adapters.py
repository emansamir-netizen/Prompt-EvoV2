"""
tests/test_adapters.py
──────────────────────────
Contract tests for adapters/: exercises the deterministic MockTargetAdapter
and the BaseTargetAdapter interface without any network access.
"""
# ruff: noqa
import pytest
from langchain_core.messages import HumanMessage

from adapters.base_adapter import (
    AdapterRateLimitError,
    AdapterResponse,
    BaseTargetAdapter,
    MockTargetAdapter,
)


def test_base_adapter_is_abstract():
    """BaseTargetAdapter must not be instantiable directly."""
    assert issubclass(MockTargetAdapter, BaseTargetAdapter)
    with pytest.raises(TypeError):
        BaseTargetAdapter()  # abstract methods are unimplemented


def test_mock_adapter_returns_configured_response():
    adapter = MockTargetAdapter(responses=["Sure, here you go."])
    out = adapter.invoke([HumanMessage(content="just say hi")])
    assert out == "Sure, here you go."
    assert adapter.get_model_id() == "mock-model"


def test_mock_adapter_invoke_full_envelope():
    adapter = MockTargetAdapter(responses=["hello world"])
    resp = adapter.invoke_full([HumanMessage(content="ping")])
    assert isinstance(resp, AdapterResponse)
    assert resp.content == "hello world"
    assert resp.model_id == "mock-model"
    assert resp.completion_tokens == 2  # "hello world" -> 2 tokens
    assert resp.finish_reason == "stop"


def test_mock_adapter_raise_on_call():
    adapter = MockTargetAdapter(responses=["ok"], raise_on_call=1)
    with pytest.raises(AdapterRateLimitError):
        adapter.invoke_full([HumanMessage(content="ping")])


def test_mock_adapter_invoke_swallows_adapter_errors():
    """invoke() (str convenience) must fail soft, returning empty string."""
    adapter = MockTargetAdapter(responses=["ok"], raise_on_call=1)
    assert adapter.invoke([HumanMessage(content="ping")]) == ""


def test_capabilities_contract():
    adapter = MockTargetAdapter()
    caps = adapter.capabilities
    assert set(caps) >= {
        "multimodal", "streaming", "system_prompt", "function_calling", "json_mode",
    }
    assert all(isinstance(v, bool) for v in caps.values())

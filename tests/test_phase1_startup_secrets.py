from __future__ import annotations

from infra.security import verify_startup_secrets
from streamlit.testing.v1 import AppTest


def test_verify_startup_secrets_rejects_placeholder_api_keys(monkeypatch):
    monkeypatch.setenv("PROMPTEVO_API_KEYS", "placeholder_promptevo_auth_key_1")

    try:
        verify_startup_secrets(dry_run=True)
    except RuntimeError as exc:
        assert "PROMPTEVO_API_KEYS" in str(exc)
    else:
        raise AssertionError("Expected placeholder API auth keys to fail startup validation")


def test_verify_startup_secrets_skips_provider_checks_in_dry_run(monkeypatch):
    monkeypatch.delenv("PROMPTEVO_API_KEYS", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "placeholder_openai_api_key")
    monkeypatch.setenv("TARGET_OPENAI_API_KEY", "placeholder_target_openai_api_key")

    verify_startup_secrets(dry_run=True)


def test_verify_startup_secrets_rejects_placeholder_target_secret(monkeypatch):
    monkeypatch.delenv("PROMPTEVO_API_KEYS", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TARGET_GROQ_API_KEY", raising=False)
    monkeypatch.delenv("TARGET_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("TARGET_OPENAI_API_KEY", "placeholder_target_openai_api_key")

    try:
        verify_startup_secrets(dry_run=False)
    except RuntimeError as exc:
        assert "TARGET_OPENAI_API_KEY" in str(exc)
    else:
        raise AssertionError("Expected placeholder target secret to fail startup validation")


def test_dashboard_startup_validation_passes_with_safe_env(monkeypatch):
    monkeypatch.setenv("PROMPTEVO_API_KEYS", "unit_test_auth_key")
    monkeypatch.setenv("OPENAI_API_KEY", "unit_test_openai_key")
    monkeypatch.setenv("TARGET_OPENAI_API_KEY", "unit_test_target_openai_key")
    monkeypatch.setenv("TARGET_ANTHROPIC_API_KEY", "unit_test_target_anthropic_key")
    monkeypatch.setenv("DRY_RUN", "false")

    app = AppTest.from_file("dashboard.py")
    app.run()

    assert len(app.exception) == 0


def test_dashboard_startup_validation_blocks_placeholder_auth(monkeypatch):
    monkeypatch.setenv("PROMPTEVO_API_KEYS", "placeholder_promptevo_auth_key_1")
    monkeypatch.setenv("OPENAI_API_KEY", "unit_test_openai_key")
    monkeypatch.setenv("TARGET_OPENAI_API_KEY", "unit_test_target_openai_key")
    monkeypatch.setenv("TARGET_ANTHROPIC_API_KEY", "unit_test_target_anthropic_key")
    monkeypatch.setenv("DRY_RUN", "false")

    app = AppTest.from_file("dashboard.py")
    app.run()

    assert len(app.exception) == 1
    assert "PROMPTEVO_API_KEYS" in app.exception[0].message


def test_verify_startup_rejects_dev_disable_auth_in_production(monkeypatch):
    """PROMPTEVO_DEV_DISABLE_AUTH=true + FASTAPI_ENV=production must abort boot.

    Previously the disable flag was silently coerced to False in production,
    which is fail-closed at the runtime check but loses the signal to the
    operator that their configuration is inconsistent.  Section A of the
    repair spec requires this combination to raise and stop launch.
    """
    monkeypatch.setenv("PROMPTEVO_API_KEYS", "unit_test_auth_key")
    monkeypatch.setenv("PROMPTEVO_DEV_DISABLE_AUTH", "true")
    monkeypatch.setenv("FASTAPI_ENV", "production")

    try:
        verify_startup_secrets(dry_run=True)
    except RuntimeError as exc:
        msg = str(exc)
        assert "PROMPTEVO_DEV_DISABLE_AUTH" in msg
        assert "production" in msg
    else:
        raise AssertionError(
            "Expected dev-disable-auth + production to fail startup validation"
        )


def test_verify_startup_allows_dev_disable_auth_in_development(monkeypatch):
    """The developer bypass must still work in non-production environments."""
    monkeypatch.setenv("PROMPTEVO_API_KEYS", "unit_test_auth_key")
    monkeypatch.setenv("PROMPTEVO_DEV_DISABLE_AUTH", "true")
    monkeypatch.setenv("FASTAPI_ENV", "development")

    verify_startup_secrets(dry_run=True)  # must not raise

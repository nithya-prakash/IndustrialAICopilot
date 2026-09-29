import pytest

from app.config import PLACEHOLDER_SECRET_KEY, InsecureConfigError, Settings

STRONG_KEY = "k" * 64


@pytest.mark.parametrize("secret_key", [PLACEHOLDER_SECRET_KEY, "too-short"])
def test_production_refuses_weak_or_placeholder_secret_key(secret_key: str) -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        secret_key=secret_key,
        anthropic_api_key="sk-live-should-never-be-printed",
    )
    with pytest.raises(InsecureConfigError, match="SECRET_KEY") as exc_info:
        settings.check_production_safety()
    # The error must not leak other settings (API keys, DB password) into logs.
    assert "sk-live-should-never-be-printed" not in str(exc_info.value)
    assert secret_key not in str(exc_info.value)


def test_production_accepts_a_real_secret_key() -> None:
    Settings(_env_file=None, app_env="production", secret_key=STRONG_KEY).check_production_safety()


def test_development_still_allows_the_placeholder() -> None:
    Settings(
        _env_file=None, app_env="development", secret_key=PLACEHOLDER_SECRET_KEY
    ).check_production_safety()

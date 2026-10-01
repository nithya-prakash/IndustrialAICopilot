import pytest

from app.config import PLACEHOLDER_SECRET_KEY, InsecureConfigError, Settings

STRONG_KEY = "k" * 64
STRONG_PASSWORD = "Xk29-vLq8-Rt71-pw"
SAFE_PRODUCTION = {
    "app_env": "production",
    "secret_key": STRONG_KEY,
    "database_url": f"postgresql+asyncpg://copilot:{STRONG_PASSWORD}@db:5432/industrial_copilot",
    "redis_url": f"redis://:{STRONG_PASSWORD}@redis:6379/0",
    "metrics_token": "m" * 40,
}


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{**SAFE_PRODUCTION, **overrides})


def test_production_accepts_fully_configured_secrets() -> None:
    _settings().check_production_safety()


@pytest.mark.parametrize(
    ("overrides", "setting_named"),
    [
        ({"secret_key": PLACEHOLDER_SECRET_KEY}, "SECRET_KEY"),
        ({"secret_key": "too-short"}, "SECRET_KEY"),
        (
            {"database_url": "postgresql+asyncpg://copilot:copilot@db:5432/industrial_copilot"},
            "DATABASE_URL",
        ),
        ({"database_url": "postgresql+asyncpg://copilot@db:5432/x"}, "DATABASE_URL"),
        ({"redis_url": "redis://redis:6379/0"}, "REDIS_URL"),
        ({"redis_url": "redis://:copilot-redis@redis:6379/0"}, "REDIS_URL"),
        ({"metrics_token": ""}, "METRICS_TOKEN"),
        ({"metrics_token": "short"}, "METRICS_TOKEN"),
    ],
)
def test_production_refuses_each_insecure_default(overrides, setting_named) -> None:
    settings = _settings(anthropic_api_key="sk-live-should-never-be-printed", **overrides)
    with pytest.raises(InsecureConfigError, match=setting_named) as exc_info:
        settings.check_production_safety()
    # Reported by setting name only — never values (logs, CI output).
    message = str(exc_info.value)
    assert "sk-live-should-never-be-printed" not in message
    for value in overrides.values():
        if value:
            assert value not in message


def test_production_reports_every_problem_at_once() -> None:
    settings = Settings(_env_file=None, app_env="production")
    with pytest.raises(InsecureConfigError) as exc_info:
        settings.check_production_safety()
    for name in ("SECRET_KEY", "DATABASE_URL", "REDIS_URL", "METRICS_TOKEN"):
        assert name in str(exc_info.value)


def test_development_still_allows_the_local_defaults() -> None:
    Settings(_env_file=None, app_env="development").check_production_safety()
